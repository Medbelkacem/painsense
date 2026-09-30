import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from './AuthProvider'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status">
        <span
          aria-hidden
          className="size-6 animate-spin rounded-full border-2 border-line-strong border-t-accent"
        />
        <span className="sr-only">Restoring your session</span>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}
