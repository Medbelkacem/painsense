import {
  Activity,
  Boxes,
  BrainCircuit,
  ClipboardList,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  ScrollText,
  ShieldCheck,
  Settings as SettingsIcon,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { DISCLAIMER } from '@/components/Disclaimer'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils/cn'

const CLINICAL = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/patients', label: 'Patients', icon: Users },
  { to: '/reports', label: 'Assessments', icon: ClipboardList },
  { to: '/analytics', label: 'Analytics', icon: Activity },
]

const PLATFORM = [
  { to: '/ai-model', label: 'Model', icon: BrainCircuit },
  { to: '/datasets', label: 'Datasets', icon: Boxes },
  { to: '/integrity', label: 'Integrity', icon: FileText },
  { to: '/security', label: 'Security', icon: ShieldCheck },
  { to: '/audit', label: 'Audit trail', icon: ScrollText },
  { to: '/architecture', label: 'Architecture', icon: Network },
]

function NavItem({
  to,
  label,
  icon: Icon,
  onNavigate,
}: {
  to: string
  label: string
  icon: typeof Users
  onNavigate: () => void
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
          isActive
            ? 'bg-accent-soft font-medium text-accent-strong'
            : 'text-body hover:bg-canvas hover:text-ink',
        )
      }
    >
      <Icon aria-hidden className="size-4 shrink-0" />
      {label}
    </NavLink>
  )
}

export function AppLayout() {
  const { user, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setMenuOpen(false), [location.pathname])

  const close = () => setMenuOpen(false)

  const nav = (
    <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-4">
      <div className="space-y-0.5">
        <p className="px-2.5 pb-1 text-[0.6875rem] font-semibold tracking-wider text-faint uppercase">
          Clinical
        </p>
        {CLINICAL.map((item) => (
          <NavItem key={item.to} {...item} onNavigate={close} />
        ))}
      </div>
      <div className="space-y-0.5">
        <p className="px-2.5 pb-1 text-[0.6875rem] font-semibold tracking-wider text-faint uppercase">
          Platform
        </p>
        {PLATFORM.map((item) => (
          <NavItem key={item.to} {...item} onNavigate={close} />
        ))}
      </div>
      <div className="mt-auto space-y-0.5">
        <NavItem to="/settings" label="Settings" icon={SettingsIcon} onNavigate={close} />
      </div>
    </nav>
  )

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>

      <aside className="hidden border-r border-line bg-surface lg:flex lg:flex-col">
        <Brand />
        {nav}
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-ink/40"
            onClick={close}
          />
          <aside className="relative flex h-full w-64 flex-col border-r border-line bg-surface">
            <Brand onClose={close} />
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-surface/95 px-4 py-2.5 backdrop-blur">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            className="rounded p-1.5 text-body hover:bg-canvas lg:hidden"
          >
            <Menu className="size-5" />
          </button>
          <div className="lg:hidden">
            <span className="text-sm font-semibold text-ink">Pain Score</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-[0.8125rem] leading-tight font-medium text-ink">
                {user?.display_name}
              </p>
              <p className="text-xs leading-tight text-muted">
                {user?.role === 'ADMIN' ? 'Administrator' : (user?.speciality ?? 'Doctor')}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void signOut()}>
              <LogOut aria-hidden className="size-4" />
              <span className="hidden sm:inline">Sign out</span>
            </Button>
          </div>
        </header>

        <main id="main" className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-6xl space-y-5">
            <Outlet />
          </div>
        </main>

        <footer className="border-t border-line px-4 py-3 sm:px-6 lg:px-8">
          <p className="mx-auto max-w-6xl text-xs leading-relaxed text-muted">{DISCLAIMER}</p>
        </footer>
      </div>
    </div>
  )
}

function Brand({ onClose }: { onClose?: () => void }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
      <img src="/icon.svg" alt="" className="size-7 rounded" />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">Pain Score</p>
        <p className="truncate text-[0.6875rem] text-muted">Clinical decision support</p>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close menu"
          className="ml-auto rounded p-1 text-muted hover:bg-canvas"
        >
          <X className="size-4" />
        </button>
      )}
    </div>
  )
}
