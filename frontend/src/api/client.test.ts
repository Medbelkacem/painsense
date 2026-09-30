import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, setAccessToken } from './client'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('api client', () => {
  beforeEach(() => {
    setAccessToken(null)
    document.cookie = 'painscore_csrf=token-from-cookie'
  })

  afterEach(() => vi.restoreAllMocks())

  it('sends the access token it was given', async () => {
    setAccessToken('an-access-token')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await api.get('/api/patients')

    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer an-access-token')
  })

  it('echoes the CSRF cookie in a header on the endpoints that need it', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/auth/logout', undefined, true)

    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('X-CSRF-Token')).toBe('token-from-cookie')
  })

  it('refreshes once and retries when the access token has expired', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'expired' }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'a-fresh-token' }))
      .mockResolvedValueOnce(jsonResponse({ code: 'PS-2026-000001' }))
    vi.stubGlobal('fetch', fetchMock)

    const body = await api.get<{ code: string }>('/api/patients/1')

    expect(body.code).toBe('PS-2026-000001')
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/patients/1',
      '/api/auth/refresh',
      '/api/patients/1',
    ])
  })

  it('gives up when the refresh also fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'expired' }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: 'no session' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.get('/api/patients')).rejects.toBeInstanceOf(ApiError)
  })

  it('does not try to refresh a failed sign-in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'Invalid credentials' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.post('/api/auth/login', { email: 'a@b.dz', password: 'x' })).rejects.toThrow(
      'Invalid credentials',
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reads a validation error into something a clinician can act on', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ['body', 'measurement', 'hr'], msg: 'Input should be less than or equal to 300' },
          ],
        },
        422,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.post('/api/assessments', {})).rejects.toThrow(
      'measurement.hr: Input should be less than or equal to 300',
    )
  })
})
