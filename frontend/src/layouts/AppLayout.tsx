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
  Settings as SettingsIcon,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { DISCLAIMER } from '@/components/Disclaimer'
import { Lockup } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils/cn'

const GROUPS = [
  {
    label: 'Clinical',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/patients', label: 'Patients', icon: Users },
      { to: '/reports', label: 'Assessments', icon: ClipboardList },
    ],
  },
  {
    label: 'Insights',
    items: [
      { to: '/analytics', label: 'Analytics', icon: Activity },
      { to: '/ai-model', label: 'AI models', icon: BrainCircuit },
      { to: '/datasets', label: 'Dataset', icon: Boxes },
    ],
  },
  {
    label: 'Trust',
    items: [
      { to: '/integrity', label: 'Integrity', icon: FileText },
      { to: '/security', label: 'Security', icon: ShieldCheck },
      { to: '/audit', label: 'Audit', icon: ScrollText },
      { to: '/architecture', label: 'Architecture', icon: Network },
    ],
  },
]

function initials(name: string) {
  return name
    .replace(/^(Dr|Pr|Mr|Ms|Mrs)\.?\s+/i, '')
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function AppLayout() {
  const { user, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  useEffect(() => setMenuOpen(false), [location.pathname])

  const nav = (
    <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
      {GROUPS.map((group) => (
        <div key={group.label} className="space-y-0.5">
          <p className="px-2.5 pb-1 text-[0.625rem] font-semibold tracking-[0.14em] text-faint uppercase">
            {group.label}
          </p>
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-body hover:bg-canvas hover:text-ink',
                )
              }
            >
              <item.icon aria-hidden className="size-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-auto space-y-0.5">
        <NavLink
          to="/settings"
          onClick={() => setMenuOpen(false)}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
              isActive
                ? 'bg-accent-soft font-medium text-accent'
                : 'text-body hover:bg-canvas hover:text-ink',
            )
          }
        >
          <SettingsIcon aria-hidden className="size-4 shrink-0" />
          Settings
        </NavLink>
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
            className="absolute inset-0 bg-brand-ink/50"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="relative flex h-full w-64 flex-col border-r border-line bg-surface">
            <Brand onClose={() => setMenuOpen(false)} />
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-surface/90 px-4 py-2.5 backdrop-blur">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            className="rounded p-1.5 text-body hover:bg-canvas lg:hidden"
          >
            <Menu className="size-5" />
          </button>
          <div className="lg:hidden">
            <Lockup markClassName="size-6" wordClassName="text-[0.9375rem]" />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <div className="flex items-center gap-2.5 rounded-full border border-line py-1 pr-3 pl-1">
              <span className="flex size-7 items-center justify-center rounded-full bg-accent-soft text-[0.6875rem] font-semibold text-accent">
                {initials(user?.display_name ?? '')}
              </span>
              <span className="hidden leading-tight sm:block">
                <span className="block text-[0.8125rem] font-medium text-ink">
                  {user?.display_name}
                </span>
                <span className="block text-[0.6875rem] text-muted">
                  {user?.role === 'ADMIN'
                    ? 'Administrator'
                    : (user?.speciality ?? user?.clinic_name ?? 'Clinician')}
                </span>
              </span>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void signOut()} aria-label="Sign out">
              <LogOut aria-hidden className="size-4" />
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
    <div className="flex items-center gap-2 border-b border-line px-4 py-3.5">
      <Lockup markClassName="size-7" wordClassName="text-[1.0625rem]" />
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
