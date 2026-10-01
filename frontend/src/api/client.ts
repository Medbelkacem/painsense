// The one place that talks to the backend.
//
// The access token is held in memory rather than in localStorage: a token in
// localStorage is readable by any script that gets injected into the page, and the
// refresh cookie the API sets is httpOnly precisely so the session can be restored
// without keeping a bearer token where script can reach it. A full page reload calls
// `refresh` and gets a new access token from that cookie.

import type { TokenResponse } from './types';

const BASE = import.meta.env.VITE_API_BASE_URL ?? '';

let accessToken: string | null = null;
let csrfToken: string | null = null;

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;

  constructor(status: number, message: string, requestId: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.requestId = requestId;
  }
}

export function setSession(token: TokenResponse | null): void {
  accessToken = token?.access_token ?? null;
  csrfToken = token?.csrf_token ?? null;
}

export function hasSession(): boolean {
  return accessToken !== null;
}

/**
 * The API sets the CSRF token in a readable cookie alongside the httpOnly refresh
 * cookie — the double-submit pattern. After a page reload the in-memory copy is gone,
 * so the cookie is the only way to present the header `/api/auth/refresh` requires.
 */
function csrfFromCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)painscore_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function readError(response: Response): Promise<ApiError> {
  let message = response.statusText || 'Request failed';
  let requestId: string | null = response.headers.get('X-Request-ID');
  try {
    const body = await response.json();
    // The API wraps failures as {error: {code, message, request_id}, detail}.
    message = body?.error?.message ?? body?.detail ?? message;
    requestId = body?.error?.request_id ?? requestId;
    if (Array.isArray(message)) {
      message = message.map((item) => item?.msg ?? String(item)).join('; ');
    }
  } catch {
    // A non-JSON body (a proxy error page, say) leaves the status text in place.
  }
  return new ApiError(response.status, String(message), requestId);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  /** Internal: stops a refresh loop when the refresh call itself returns 401. */
  retryOnUnauthorised?: boolean;
}

/**
 * A `FormData` body is passed through untouched and its content type is left unset.
 * Setting `multipart/form-data` by hand omits the boundary the browser generates, and the
 * server then cannot find the parts — so the one correct move is to say nothing.
 */
function isMultipart(body: unknown): body is FormData {
  return typeof FormData !== 'undefined' && body instanceof FormData;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, retryOnUnauthorised = true } = options;
  const headers: Record<string, string> = {};
  const multipart = isMultipart(body);
  if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (method !== 'GET') {
    const csrf = csrfToken ?? csrfFromCookie();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
    signal,
  });

  if (response.status === 401 && retryOnUnauthorised && path !== '/api/auth/refresh') {
    const renewed = await refresh();
    if (renewed) return request<T>(path, { ...options, retryOnUnauthorised: false });
  }
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Fetch a binary body and hand it to the browser as a download.
 *
 * Separate from `request` because that one parses JSON, and a report is a PDF. The object
 * URL is revoked on the next tick: revoking it synchronously races the download in Safari,
 * and never revoking it holds the whole file in memory for the life of the tab.
 */
export async function download(
  path: string,
  fallbackName: string,
  options: { method?: string; body?: unknown } = {},
): Promise<void> {
  const { method = 'POST', body } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const csrf = csrfToken ?? csrfFromCookie();
  if (csrf) headers['X-CSRF-Token'] = csrf;

  let response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401) {
    const renewed = await refresh();
    if (renewed) {
      headers.Authorization = `Bearer ${renewed.access_token}`;
      headers['X-CSRF-Token'] = renewed.csrf_token;
      response = await fetch(`${BASE}${path}`, {
        method,
        headers,
        credentials: 'include',
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    }
  }
  if (!response.ok) throw await readError(response);

  // The server names the file; the caller's name is the fallback.
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = match ? match[1] : fallbackName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const token = await request<TokenResponse>('/api/auth/login', {
    method: 'POST',
    body: { email, password },
    retryOnUnauthorised: false,
  });
  setSession(token);
  return token;
}

let refreshing: Promise<TokenResponse | null> | null = null;

/**
 * Exchange the httpOnly refresh cookie for a new access token.
 *
 * One exchange at a time. A refresh token is single-use, and two callers racing for it
 * (React mounting the session provider twice in development, or two expired requests
 * firing together) would spend it once and then be signed out by the second attempt.
 */
export function refresh(): Promise<TokenResponse | null> {
  if (refreshing) return refreshing;
  refreshing = request<TokenResponse>('/api/auth/refresh', {
    method: 'POST',
    retryOnUnauthorised: false,
  })
    .then((token) => {
      setSession(token);
      return token;
    })
    .catch(() => {
      setSession(null);
      return null;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function logout(): Promise<void> {
  try {
    await request<void>('/api/auth/logout', { method: 'POST', retryOnUnauthorised: false });
  } finally {
    setSession(null);
  }
}
