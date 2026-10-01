import type { LucideIcon } from 'lucide-react';
import {
  Activity, Binary, ClipboardList, CloudDownload, Database, FolderClosed, LayoutDashboard,
  LineChart, Link2, ScrollText, Settings, ShieldCheck, UserRound, Users, UsersRound,
} from 'lucide-react';
import type { Role } from '../api/types';

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** Shown as a small count on the rail: work waiting on this clinician. */
  badge?: number;
  /** Who sees the entry. Absent means every signed-in account. */
  roles?: readonly Role[];
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

const CLINICAL: Role[] = ['SUPER_ADMIN', 'CLINIC_ADMIN', 'DOCTOR', 'NURSE'];
const ADMIN: Role[] = ['SUPER_ADMIN', 'CLINIC_ADMIN'];
const RESEARCH: Role[] = ['SUPER_ADMIN', 'CLINIC_ADMIN', 'RESEARCHER'];
const AUDIT: Role[] = ['SUPER_ADMIN', 'CLINIC_ADMIN', 'AUDITOR'];

/**
 * The rail. Grouping is the navigation: a clinician looking for a patient never has to
 * read past CLINICAL, and the governance screens stay together under TRUST where an
 * auditor expects them. A patient account gets one entry, its own record.
 */
export const navGroups: NavGroup[] = [
  {
    title: 'Clinical',
    items: [
      { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard, roles: CLINICAL },
      { label: 'Patients', path: '/patients', icon: Users, roles: CLINICAL },
      { label: 'Assessments', path: '/assessments', icon: ClipboardList, roles: CLINICAL },
      { label: 'My record', path: '/my-record', icon: UserRound, roles: ['PATIENT'] },
    ],
  },
  {
    title: 'Insights',
    items: [
      { label: 'Analytics', path: '/analytics', icon: LineChart, roles: CLINICAL },
      { label: 'AI models', path: '/ai-models', icon: Activity, roles: RESEARCH },
      { label: 'Dataset', path: '/dataset', icon: Database, roles: RESEARCH },
    ],
  },
  {
    title: 'Records',
    items: [
      { label: 'Documents', path: '/documents', icon: FolderClosed, roles: CLINICAL },
      { label: 'External datasets', path: '/external-datasets', icon: CloudDownload, roles: RESEARCH },
    ],
  },
  {
    title: 'Trust',
    items: [
      { label: 'Integrity', path: '/security', icon: ShieldCheck, roles: AUDIT },
      { label: 'Audit', path: '/audit', icon: ScrollText, roles: [...CLINICAL, 'AUDITOR'] },
      { label: 'Accounts', path: '/accounts', icon: UsersRound, roles: ADMIN },
    ],
  },
];

export const settingsItem: NavItem = { label: 'Settings', path: '/settings', icon: Settings };

export function visibleTo(role: Role | undefined): NavGroup[] {
  return navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.roles || (role && item.roles.includes(role))),
    }))
    .filter((group) => group.items.length > 0);
}

export const allNavItems: NavItem[] = [
  ...navGroups.flatMap((group) => group.items),
  settingsItem,
];

/** Icons the command palette uses for result rows that are not nav entries. */
export const resultIcons = { patient: Users, assessment: ClipboardList, link: Link2, model: Binary };

/** "Assessments > New assessment" for the top bar. */
export function breadcrumbFor(pathname: string): { label: string; group?: string } {
  const item = allNavItems.find((entry) => pathname.startsWith(entry.path));
  if (!item) return { label: 'Workspace' };
  const group = navGroups.find((entry) => entry.items.includes(item));
  return { label: item.label, group: group?.title };
}
