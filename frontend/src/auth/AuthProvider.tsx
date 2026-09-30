import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api, setAccessToken } from '@/api/client'
import type { TokenResponse, User } from '@/api/types'

interface AuthState {
  user: User | null
  ready: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** Adopt a session obtained elsewhere, such as the one registration returns. */
  refresh: (user: User) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const queryClient = useQueryClient()

  useEffect(() => {
    // The access token lives in memory, so a reload starts without one. The refresh cookie
    // is what decides whether the session is still valid.
    let active = true
    api
      .restore()
      .then(async (restored) => {
        if (!active) return
        if (restored) setUser(await api.get<User>('/api/auth/me'))
      })
      .catch(() => undefined)
      .finally(() => active && setReady(true))
    return () => {
      active = false
    }
  }, [])

  const signIn = useCallback(
    async (email: string, password: string) => {
      const response = await api.post<TokenResponse>('/api/auth/login', { email, password })
      setAccessToken(response.access_token)
      setUser(response.user)
      queryClient.clear()
    },
    [queryClient],
  )

  const signOut = useCallback(async () => {
    try {
      await api.post('/api/auth/logout', undefined, true)
    } finally {
      setAccessToken(null)
      setUser(null)
      queryClient.clear()
    }
  }, [queryClient])

  const refresh = useCallback(
    (next: User) => {
      setUser(next)
      queryClient.clear()
    },
    [queryClient],
  )

  const value = useMemo(
    () => ({ user, ready, signIn, signOut, refresh }),
    [user, ready, signIn, signOut, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
