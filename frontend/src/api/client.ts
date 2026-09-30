import type { TokenResponse } from './types'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/**
 * The access token is held in memory only.
 *
 * Nothing about a signed-in session survives in localStorage, so a script that manages to
 * run on the page finds no token to steal and a closed tab leaves none behind. The session
 * is re-established on load from the HttpOnly refresh cookie instead.
 */
let accessToken: string | null = null

export const setAccessToken = (token: string | null) => {
  accessToken = token
}
export const getAccessToken = () => accessToken

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)painscore_csrf=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function parse(response: Response) {
  const type = response.headers.get('content-type') ?? ''
  if (type.includes('application/json')) return response.json()
  if (type.includes('application/pdf')) return response.blob()
  return response.text()
}

function messageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
        return field ? `${field}: ${item.msg}` : (item.msg ?? '')
      })
      .filter(Boolean)
      .join('. ')
  }
  return status === 401 ? 'Your session has ended. Sign in again.' : `Request failed (${status})`
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Set for the endpoints that act on the refresh cookie. */
  csrf?: boolean
}

let refreshing: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const response = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': csrfToken() },
      })
      if (!response.ok) return false
      const body = (await response.json()) as TokenResponse
      setAccessToken(body.access_token)
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

async function send(path: string, options: RequestOptions, retry: boolean): Promise<unknown> {
  const headers = new Headers(options.headers)
  const isFormData = options.body instanceof FormData
  if (options.body !== undefined && !isFormData) headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (options.csrf) headers.set('X-CSRF-Token', csrfToken())

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'include',
    body: isFormData ? (options.body as FormData) : JSON.stringify(options.body),
  })

  if (response.status === 401 && retry && path !== '/api/auth/login') {
    if (await refreshSession()) return send(path, options, false)
  }
  if (response.status === 204) return null

  const body = await parse(response)
  if (!response.ok) throw new ApiError(response.status, messageFrom(response.status, body), body)
  return body
}

export const api = {
  get: <T>(path: string) => send(path, { method: 'GET' }, true) as Promise<T>,
  post: <T>(path: string, body?: unknown, csrf = false) =>
    send(path, { method: 'POST', body, csrf }, true) as Promise<T>,
  patch: <T>(path: string, body: unknown) =>
    send(path, { method: 'PATCH', body }, true) as Promise<T>,
  upload: <T>(path: string, form: FormData) =>
    send(path, { method: 'POST', body: form }, true) as Promise<T>,
  restore: refreshSession,
}
