import React, { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Bell, Check, ChevronDown, ChevronRight, LogOut, Menu as MenuIcon, Moon,
  PanelLeftClose, PanelLeftOpen, Search, Settings as SettingsIcon, Sun,
  TriangleAlert, UserRound, X,
} from 'lucide-react';
import { Logo, Mark } from '../../ui/Logo';
import { IconButton } from '../../ui/Button';
import { Menu } from '../../ui/Dropdown';
import { Pill } from '../../ui/Pill';
import { CommandPalette } from '../CommandPalette';
import { breadcrumbFor, settingsItem, visibleTo, type NavItem } from '../nav-model';
import { useSession } from '../../auth/session';
import { useTheme } from '../../theme';
import { initials, whenRelative } from '../../lib/format';
import { DISCLAIMER } from '../../lib/clinical';
import { useQuery } from '../../api/hooks';
import type { Analytics } from '../../api/types';
import { cx } from '../../lib/cx';

const ROLE_WORD: Record<string, string> = {
  SUPER_ADMIN: 'Platform administrator',
  CLINIC_ADMIN: 'Clinic administrator',
  DOCTOR: 'Doctor',
  NURSE: 'Nurse',
  PATIENT: 'Patient',
  RESEARCHER: 'Researcher',
  AUDITOR: 'Auditor',
};

const CLINICAL = new Set(['SUPER_ADMIN', 'CLINIC_ADMIN', 'DOCTOR', 'NURSE']);

const RAIL_KEY = 'painsense.rail';

const RailLink: React.FC<{ item: NavItem; collapsed: boolean; onNavigate: () => void }> = ({
  item,
  collapsed,
  onNavigate,
}) => (
  <NavLink
    to={item.path}
    onClick={onNavigate}
    title={collapsed ? item.label : undefined}
    className={({ isActive }) =>
      cx(
        'group relative flex h-9 items-center gap-2.5 rounded-[10px] text-[13px] font-medium transition-colors',
        collapsed ? 'justify-center px-0' : 'px-2.5',
        isActive
          ? 'bg-accent-wash text-accent-ink'
          : 'text-soft hover:bg-sunken hover:text-ink',
      )
    }
  >
    {({ isActive }) => (
      <>
        {/* The notch on the rail edge — the thing that makes the active row readable
            at a glance when the sidebar is collapsed to icons. */}
        <span
          aria-hidden
          className={cx(
            'absolute -left-3 h-5 w-[3px] rounded-r-full bg-accent transition-opacity',
            isActive ? 'opacity-100' : 'opacity-0',
          )}
        />
        <item.icon className={cx('h-4 w-4 shrink-0', isActive ? 'text-accent' : 'text-faint')} />
        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
        {item.badge !== undefined &&
          (collapsed ? (
            <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-warn" />
          ) : (
            <span className="rounded-full bg-warn/15 px-1.5 text-[10px] font-semibold text-warn tabular-nums">
              {item.badge}
            </span>
          ))}
      </>
    )}
  </NavLink>
);

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useSession();
  const theme = useTheme();

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(RAIL_KEY) === '1');
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const clinical = CLINICAL.has(user?.role ?? '');
  const groups = visibleTo(user?.role);

  useEffect(() => {
    localStorage.setItem(RAIL_KEY, collapsed ? '1' : '0');
  }, [collapsed]);

  // The drawer is a mobile affordance; leaving it open across a route change traps the
  // page underneath it.
  useEffect(() => setDrawer(false), [location.pathname]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPalette((open) => !open);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const crumb = breadcrumbFor(location.pathname);

  // One request feeds the review bell and the rail badge. It polls slowly: an assessment
  // signed on another workstation should show up here, but not at the cost of a request
  // a second from every open tab. A patient account has no overview to ask for.
  const analytics = useQuery<Analytics>(clinical ? '/api/analytics' : null, 120);
  const waiting = analytics.data?.assessments_awaiting_validation ?? 0;
  const review = (analytics.data?.recent_assessments ?? [])
    .filter((item) => item.status !== 'VALIDATED')
    .slice(0, 4);

  const sidebar = (
    <aside
      className={cx(
        'flex h-full shrink-0 flex-col border-r border-hairline bg-surface transition-[width] duration-200',
        collapsed ? 'w-[68px]' : 'w-[232px]',
      )}
    >
      <div
        className={cx(
          'flex h-14 shrink-0 items-center border-b border-hairline',
          collapsed ? 'justify-center px-2' : 'justify-between pr-2 pl-4',
        )}
      >
        <Link to="/dashboard" aria-label="PainSense AI">
          {collapsed ? <Mark className="h-7 w-7" /> : <Logo size="md" showAi={false} />}
        </Link>
        <button
          type="button"
          onClick={() => setDrawer(false)}
          aria-label="Close navigation"
          className="grid h-8 w-8 place-items-center rounded-lg text-faint hover:bg-sunken lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav className="flex-1 space-y-4 overflow-x-hidden overflow-y-auto px-3 py-4">
        {groups.map((group) => (
          <div key={group.title} className="space-y-0.5">
            {collapsed ? (
              <div className="mx-auto mb-1.5 h-px w-6 bg-hairline" />
            ) : (
              <p className="eyebrow px-2.5 pb-1">{group.title}</p>
            )}
            {group.items.map((item) => (
              <RailLink
                key={item.path}
                item={
                  item.path === '/assessments' && waiting > 0
                    ? { ...item, badge: waiting }
                    : item
                }
                collapsed={collapsed}
                onNavigate={() => setDrawer(false)}
              />
            ))}
          </div>
        ))}
      </nav>

      <div className="space-y-0.5 border-t border-hairline px-3 py-3">
        <RailLink item={settingsItem} collapsed={collapsed} onNavigate={() => setDrawer(false)} />
        {/* The collapse control sits with Settings rather than beside the logo: it stays
            reachable at 68px wide, where the header has room for the mark alone. */}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={cx(
            'hidden h-9 w-full items-center gap-2.5 rounded-[10px] text-[13px] font-medium text-soft transition-colors hover:bg-sunken hover:text-ink lg:flex',
            collapsed ? 'justify-center px-0' : 'px-2.5',
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4 text-faint" />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4 text-faint" />
              <span>Collapse</span>
            </>
          )}
        </button>
        {!collapsed && (
          <p className="px-2.5 pt-2 text-[10px] leading-relaxed text-faint">
            AI-assisted prototype.
            <br />
            Not a medical diagnosis.
          </p>
        )}
      </div>
    </aside>
  );

  return (
    <div className="flex h-dvh overflow-hidden bg-canvas text-ink">
      <div className="hidden lg:flex">{sidebar}</div>

      {drawer && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div className="animate-[ps-pop_150ms_ease-out]">{sidebar}</div>
          <button
            type="button"
            aria-label="Close navigation"
            className="flex-1 bg-[#0b1b33]/40"
            onClick={() => setDrawer(false)}
          />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-hairline bg-surface px-3 sm:px-5">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            aria-label="Open navigation"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-mute hover:bg-sunken lg:hidden"
          >
            <MenuIcon className="h-4.5 w-4.5" />
          </button>

          <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-[13px] md:flex">
            {crumb.group && (
              <>
                <span className="text-mute">{crumb.group}</span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-faint" />
              </>
            )}
            <span className="truncate font-medium text-ink">{crumb.label}</span>
          </nav>

          {clinical && (
            <button
              type="button"
              onClick={() => setPalette(true)}
              className="mx-auto flex h-9 w-full max-w-md items-center gap-2 rounded-[10px] border border-hairline bg-sunken px-3 text-[13px] text-faint transition-colors hover:border-hairline-strong"
            >
              <Search className="h-4 w-4 shrink-0" />
              <span className="truncate">Search patients and pages</span>
              <kbd className="ml-auto hidden shrink-0 rounded border border-hairline bg-surface px-1 font-sans text-[10px] leading-4 sm:block">
                Ctrl K
              </kbd>
            </button>
          )}

          <div className="ml-auto flex shrink-0 items-center gap-2">
            <IconButton
              label={theme.resolved === 'dark' ? 'Switch to light' : 'Switch to dark'}
              onClick={theme.toggle}
            >
              {theme.resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </IconButton>

            {clinical && (
            <Menu
              width="w-[19rem]"
              header={
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-ink">Needs review</span>
                  <Pill tone="warn" size="xs">
                    {waiting}
                  </Pill>
                </div>
              }
              entries={[
                ...review.map((item) => ({
                  label: `${item.patient_code} · ${
                    item.estimated_pain === null
                      ? 'not estimated'
                      : `AI ${item.estimated_pain.toFixed(1)}`
                  }${item.self_report === null ? '' : ` vs reported ${item.self_report}`}`,
                  icon: <TriangleAlert className="h-3.5 w-3.5 text-warn" />,
                  hint: whenRelative(new Date(item.created_at)),
                  onSelect: () => navigate('/assessments'),
                })),
                null,
                {
                  label: 'Open the review queue',
                  icon: <Check className="h-3.5 w-3.5" />,
                  onSelect: () => navigate('/assessments'),
                },
              ]}
              trigger={({ toggle }) => (
                <button
                  type="button"
                  onClick={toggle}
                  aria-label="Notifications"
                  className="relative grid h-9 w-9 shrink-0 place-items-center rounded-[10px] border border-hairline bg-surface text-mute transition-colors hover:border-hairline-strong hover:text-ink"
                >
                  <Bell className="h-4 w-4" />
                  {review.length > 0 && (
                    <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full border-2 border-surface bg-warn" />
                  )}
                </button>
              )}
            />
            )}

            <Menu
              width="w-64"
              header={
                <div>
                  <p className="text-[13px] font-semibold text-ink">
                    {user?.display_name ?? '—'}
                  </p>
                  <p className="truncate text-xs text-mute">{user?.email}</p>
                  {user?.speciality && (
                    <Pill tone="accent" size="xs" className="mt-2">
                      {user.speciality}
                    </Pill>
                  )}
                </div>
              }
              entries={[
                {
                  label: 'Profile and credentials',
                  icon: <UserRound className="h-3.5 w-3.5" />,
                  onSelect: () => navigate('/settings'),
                },
                {
                  label: 'Settings',
                  icon: <SettingsIcon className="h-3.5 w-3.5" />,
                  onSelect: () => navigate('/settings'),
                },
                {
                  label: theme.preference === 'system' ? 'Theme follows the system' : `Theme: ${theme.preference}`,
                  icon: <Moon className="h-3.5 w-3.5" />,
                  onSelect: () =>
                    theme.setPreference(theme.preference === 'system' ? 'light' : theme.preference === 'light' ? 'dark' : 'system'),
                },
                null,
                {
                  label: 'Sign out',
                  icon: <LogOut className="h-3.5 w-3.5" />,
                  tone: 'danger' as const,
                  onSelect: () => void signOut().finally(() => navigate('/login', { replace: true })),
                },
              ]}
              trigger={({ open, toggle }) => (
                <button
                  type="button"
                  onClick={toggle}
                  className={cx(
                    'flex h-9 items-center gap-2 rounded-[10px] border px-1.5 transition-colors',
                    open ? 'border-hairline-strong bg-sunken' : 'border-transparent hover:bg-sunken',
                  )}
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-clinical text-[11px] font-semibold text-white dark:bg-accent dark:text-[#04121f]">
                    {initials(user?.display_name)}
                  </span>
                  <span className="hidden text-left leading-tight sm:block">
                    <span className="block text-[12px] font-semibold text-ink">
                      {user?.display_name ?? ''}
                    </span>
                    <span className="block text-[10px] text-mute">
                      {user?.speciality ?? ROLE_WORD[user?.role ?? ''] ?? ''}
                    </span>
                  </span>
                  <ChevronDown
                    className={cx('h-3.5 w-3.5 shrink-0 text-faint transition-transform', open && 'rotate-180')}
                  />
                </button>
              )}
            />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] space-y-5 px-4 py-6 sm:px-6">
            <Outlet />
          </div>
          <footer className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center justify-between gap-2 px-4 pb-8 text-[11px] text-faint sm:px-6">
            <span>{DISCLAIMER}</span>
            <span>PainSense AI</span>
          </footer>
        </main>
      </div>

      {clinical && <CommandPalette open={palette} onClose={() => setPalette(false)} />}
    </div>
  );
};
