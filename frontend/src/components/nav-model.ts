import type { LucideIcon } from 'lucide-react';
import {
  Activity, Binary, BrainCircuit, ClipboardList, CloudDownload, Database, FileText,
  FolderClosed, LayoutDashboard, LineChart, Link2, ScrollText, Settings, ShieldCheck,
  Users,
} from 'lucide-react';

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** Shown as a small count on the rail — work waiting on this clinician. */
  badge?: number;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

/**
 * The rail. Grouping is the navigation: a clinician looking for a patient never has to
 * read past CLINICAL, and the governance screens stay together under TRUST where an
 * auditor expects them.
 */
export const navGroups: NavGroup[] = [
  {
    title: 'Clinical',
    items: [
      { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
      { label: 'Patients', path: '/patients', icon: Users },
      { label: 'Assessments', path: '/assessments', icon: ClipboardList },
      { label: 'AI analysis', path: '/ai-analysis', icon: BrainCircuit },
    ],
  },
  {
    title: 'Insights',
    items: [
      { label: 'Analytics', path: '/analytics', icon: LineChart },
      { label: 'AI models', path: '/ai-models', icon: Activity },
      { label: 'Dataset', path: '/dataset', icon: Database },
      { label: 'Reports', path: '/reports', icon: FileText },
    ],
  },
  {
    title: 'Records',
    items: [
      { label: 'Documents', path: '/documents', icon: FolderClosed },
      { label: 'External datasets', path: '/external-datasets', icon: CloudDownload },
    ],
  },
  {
    title: 'Trust',
    items: [
      { label: 'Integrity', path: '/security', icon: ShieldCheck },
      { label: 'Audit', path: '/audit', icon: ScrollText },
    ],
  },
];

export const settingsItem: NavItem = { label: 'Settings', path: '/settings', icon: Settings };

export const allNavItems: NavItem[] = [
  ...navGroups.flatMap((group) => group.items),
  settingsItem,
];

/** Icons the command palette uses for result rows that are not nav entries. */
export const resultIcons = { patient: Users, assessment: ClipboardList, link: Link2, model: Binary };

/** "Assessments › New assessment › Pain" for the top bar. */
export function breadcrumbFor(pathname: string): { label: string; group?: string } {
  const item = allNavItems.find((entry) => pathname.startsWith(entry.path));
  if (!item) return { label: 'Workspace' };
  const group = navGroups.find((entry) => entry.items.includes(item));
  return { label: item.label, group: group?.title };
}
