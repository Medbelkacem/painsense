import React, { useCallback, useEffect, useState } from 'react';
import {
  Check, KeyRound, LogOut, Monitor, MonitorSmartphone, Moon, Palette, ShieldCheck, Sun, UserRound,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type { Role, User } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, type Tone } from '../ui/Pill';
import { Select } from '../ui/Dropdown';
import { TextField } from '../ui/Field';
import { useTheme, type ThemePreference } from '../theme';
import { useSession } from '../auth/session';
import { cx } from '../lib/cx';
import { whenShort } from '../lib/format';

const PANES = [
  { key: 'profile', label: 'Profile', icon: UserRound },
  { key: 'security', label: 'Security', icon: ShieldCheck },
  { key: 'appearance', label: 'Appearance', icon: Palette },
] as const;

type Pane = (typeof PANES)[number]['key'];

export const ROLE_LABEL: Record<Role, string> = {
  SUPER_ADMIN: 'Platform administrator',
  CLINIC_ADMIN: 'Clinic administrator',
  DOCTOR: 'Doctor',
  NURSE: 'Nurse',
  PATIENT: 'Patient',
  RESEARCHER: 'Researcher',
  AUDITOR: 'Auditor',
};

export const ROLE_TONE: Record<Role, Tone> = {
  SUPER_ADMIN: 'danger',
  CLINIC_ADMIN: 'warn',
  DOCTOR: 'accent',
  NURSE: 'teal',
  PATIENT: 'neutral',
  RESEARCHER: 'violet',
  AUDITOR: 'ok',
};

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
  { value: 'ar', label: 'العربية' },
] as const;

const MIN_PASSWORD = 12;

// What GET /api/auth/sessions returns. Not in types.ts because nothing else reads it.
interface SessionOut {
  id: string;
  issued_at: string;
  expires_at: string;
  last_used_at: string | null;
  user_agent: string | null;
  client_ip: string | null;
}

/** A miniature of the workspace, so the theme choice is shown rather than described. */
const ThemeCard: React.FC<{
  value: ThemePreference;
  current: ThemePreference;
  onPick: (value: ThemePreference) => void;
}> = ({ value, current, onPick }) => {
  const label = value === 'system' ? 'System' : value === 'dark' ? 'Dark' : 'Light';
  const Icon = value === 'system' ? Monitor : value === 'dark' ? Moon : Sun;
  const dark = value === 'dark';

  return (
    <button
      type="button"
      onClick={() => onPick(value)}
      className={cx(
        'group flex-1 rounded-xl border p-2 text-left transition-colors',
        current === value ? 'border-accent bg-accent-wash' : 'border-hairline hover:border-hairline-strong',
      )}
    >
      <div
        className={cx(
          'flex h-20 gap-1 overflow-hidden rounded-lg border p-1.5',
          value === 'system'
            ? 'border-[#cbd5e4] bg-gradient-to-r from-[#f2f5fa] from-50% to-[#0d1829] to-50%'
            : dark
              ? 'border-[#1c2b45] bg-[#060b14]'
              : 'border-[#e3e8f2] bg-[#f2f5fa]',
        )}
      >
        <div className={cx('w-5 shrink-0 rounded-sm', dark ? 'bg-[#0d1829]' : 'bg-white')} />
        <div className="flex flex-1 flex-col gap-1">
          <div className={cx('h-2 rounded-sm', dark ? 'bg-[#0d1829]' : 'bg-white')} />
          <div className={cx('flex-1 rounded-sm', dark ? 'bg-[#0d1829]' : 'bg-white')} />
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 px-0.5">
        <Icon className="h-3.5 w-3.5 text-faint" />
        <span className="text-[12.5px] font-medium text-ink">{label}</span>
        {current === value && <Check className="ml-auto h-3.5 w-3.5 text-accent" />}
      </div>
    </button>
  );
};

const Notice: React.FC<{ tone: 'ok' | 'danger'; children: React.ReactNode }> = ({
  tone,
  children,
}) => (
  <p
    className={cx(
      'rounded-[10px] border px-3 py-2 text-[12px]',
      tone === 'ok'
        ? 'border-ok/25 bg-ok/8 text-ok'
        : 'border-danger/25 bg-danger/8 text-danger',
    )}
  >
    {children}
  </p>
);

type ProfileField =
  | 'display_name'
  | 'clinic_name'
  | 'phone'
  | 'speciality'
  | 'registration_number'
  | 'preferred_language';

type ProfileDraft = Record<ProfileField, string>;

const draftOf = (user: User): ProfileDraft => ({
  display_name: user.display_name,
  clinic_name: user.clinic_name ?? '',
  phone: user.phone ?? '',
  speciality: user.speciality ?? '',
  registration_number: user.registration_number ?? '',
  preferred_language: user.preferred_language,
});

const Profile: React.FC<{ user: User }> = ({ user }) => {
  const { refreshUser } = useSession();
  const [draft, setDraft] = useState<ProfileDraft>(() => draftOf(user));
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(draftOf(user));
  }, [user]);

  // Only what actually changed goes over the wire, so the audit entry lists the
  // fields that were edited rather than all six every time.
  const changes = (Object.keys(draft) as ProfileField[]).reduce<Partial<ProfileDraft>>(
    (acc, field) => {
      const before = draftOf(user)[field];
      const after = draft[field].trim();
      if (after !== before) acc[field] = after;
      return acc;
    },
    {},
  );
  const dirty = Object.keys(changes).length > 0;

  const set = (field: ProfileField) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setSaved(false);
    setDraft((current) => ({ ...current, [field]: event.target.value }));
  };

  const save = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await request<User>('/api/auth/me', { method: 'PATCH', body: changes });
      await refreshUser();
      setSaved(true);
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The profile could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <CardHead
        title="Profile"
        sub="Shown on reports and in the audit trail."
        action={<Pill tone={ROLE_TONE[user.role]}>{ROLE_LABEL[user.role]}</Pill>}
      />

      {failure && (
        <div className="mt-4">
          <Notice tone="danger">{failure}</Notice>
        </div>
      )}
      {saved && !dirty && (
        <div className="mt-4">
          <Notice tone="ok">Saved.</Notice>
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TextField label="Display name" value={draft.display_name} onChange={set('display_name')} />
        <TextField
          label="Email"
          value={user.email}
          readOnly
          hint="The address you sign in with."
          className="[&_input]:text-mute"
        />
        <TextField label="Clinic" value={draft.clinic_name} onChange={set('clinic_name')} />
        <TextField label="Telephone" value={draft.phone} onChange={set('phone')} />
        <TextField label="Speciality" value={draft.speciality} onChange={set('speciality')} />
        <TextField
          label="Registration number"
          value={draft.registration_number}
          onChange={set('registration_number')}
        />
        <div className="space-y-1.5">
          <span className="block text-xs font-medium text-soft">Preferred language</span>
          <Select
            label="Language"
            clearable={false}
            className="w-full [&>button]:w-full"
            options={LANGUAGES}
            value={draft.preferred_language}
            onChange={(value) => {
              if (value === null) return;
              setSaved(false);
              setDraft((current) => ({ ...current, preferred_language: value }));
            }}
          />
        </div>
      </div>

      <div className="mt-5 flex items-center justify-end gap-2 border-t border-hairline pt-4">
        {dirty && (
          <Button variant="ghost" onClick={() => setDraft(draftOf(user))} disabled={busy}>
            Discard
          </Button>
        )}
        <Button
          variant="primary"
          disabled={!dirty || busy || draft.display_name.trim().length < 2}
          onClick={() => void save()}
        >
          {busy ? 'Saving…' : 'Save profile'}
        </Button>
      </div>
    </Card>
  );
};

const ChangePassword: React.FC = () => {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD;
  const mismatch = again.length > 0 && again !== next;
  const ready =
    current.length > 0 && next.length >= MIN_PASSWORD && again === next && next !== current;

  const submit = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    setDone(false);
    try {
      await request<void>('/api/auth/me/password', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      });
      setCurrent('');
      setNext('');
      setAgain('');
      setDone(true);
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The password could not be changed.');
    } finally {
      setBusy(false);
    }
  }, [current, next]);

  return (
    <Card className="p-5">
      <CardHead
        title="Password"
        sub={`At least ${MIN_PASSWORD} characters. Every other device is signed out when it changes.`}
      />

      {failure && (
        <div className="mt-4">
          <Notice tone="danger">{failure}</Notice>
        </div>
      )}
      {done && (
        <div className="mt-4">
          <Notice tone="ok">Password changed. This device stays signed in.</Notice>
        </div>
      )}

      <form
        className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && !busy) void submit();
        }}
      >
        <TextField
          label="Current password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          error={
            tooShort
              ? `${MIN_PASSWORD - next.length} more character${MIN_PASSWORD - next.length === 1 ? '' : 's'}`
              : next.length > 0 && next === current
                ? 'Same as the current password'
                : null
          }
        />
        <TextField
          label="Repeat new password"
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(event) => setAgain(event.target.value)}
          error={mismatch ? 'Does not match' : null}
        />
        <div className="flex justify-end sm:col-span-3">
          <Button
            type="submit"
            variant="primary"
            icon={<KeyRound className="h-4 w-4" />}
            disabled={!ready || busy}
          >
            {busy ? 'Changing…' : 'Change password'}
          </Button>
        </div>
      </form>
    </Card>
  );
};

/** "Firefox on Linux" out of a user-agent string; the raw string stays in the title. */
function describeAgent(agent: string | null): string {
  if (!agent) return 'Unknown device';
  let browser = agent.split('/')[0].slice(0, 24);
  if (agent.includes('Edg/')) browser = 'Edge';
  else if (agent.includes('OPR/')) browser = 'Opera';
  else if (agent.includes('Firefox/')) browser = 'Firefox';
  else if (agent.includes('Chrome/')) browser = 'Chrome';
  else if (agent.includes('Safari/')) browser = 'Safari';

  let os: string | null = null;
  if (agent.includes('Android')) os = 'Android';
  else if (/iPhone|iPad/.test(agent)) os = 'iOS';
  else if (agent.includes('Windows')) os = 'Windows';
  else if (agent.includes('Mac OS X')) os = 'macOS';
  else if (agent.includes('Linux')) os = 'Linux';

  return os ? `${browser} on ${os}` : browser;
}

const Sessions: React.FC = () => {
  const { signOut } = useSession();
  const { data, error, loading, reload } = useQuery<SessionOut[]>('/api/auth/sessions');
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const revoke = async (id: string) => {
    setPending(id);
    setFailure(null);
    try {
      await request<void>(`/api/auth/sessions/${id}`, { method: 'DELETE' });
      reload();
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The session could not be revoked.');
    } finally {
      setPending(null);
    }
  };

  const everywhere = async () => {
    setPending('all');
    setFailure(null);
    try {
      await request<void>('/api/auth/logout-all', { method: 'POST' });
      await signOut();
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'Could not sign out everywhere.');
      setPending(null);
    }
  };

  const rows = data ?? [];

  return (
    <Card className="p-5">
      <CardHead
        title="Active sessions"
        sub="Every device holding a refresh token for this account, including this one."
        action={
          <Button
            variant="danger"
            size="sm"
            icon={<LogOut className="h-3.5 w-3.5" />}
            disabled={pending !== null}
            onClick={() => void everywhere()}
          >
            Sign out everywhere
          </Button>
        }
      />

      {(error || failure) && (
        <div className="mt-4">
          <Notice tone="danger">{failure ?? error}</Notice>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<MonitorSmartphone className="h-5 w-5" />}
          title={loading ? 'Loading…' : 'No active session'}
        />
      ) : (
        <ul className="mt-4 divide-y divide-hairline">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-3 py-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-sunken text-faint">
                <MonitorSmartphone className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-ink" title={row.user_agent ?? undefined}>
                  {describeAgent(row.user_agent)}
                  {row.client_ip && <span className="ml-2 font-normal text-faint">{row.client_ip}</span>}
                </p>
                <p className="mt-0.5 text-[11.5px] text-mute">
                  Signed in {whenShort(new Date(row.issued_at))}
                  {row.last_used_at && ` · last used ${whenShort(new Date(row.last_used_at))}`}
                  {` · expires ${whenShort(new Date(row.expires_at))}`}
                </p>
              </div>
              <Button
                size="sm"
                disabled={pending !== null}
                onClick={() => void revoke(row.id)}
              >
                {pending === row.id ? 'Revoking…' : 'Revoke'}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
};

export const Settings: React.FC = () => {
  const theme = useTheme();
  const { user } = useSession();
  const [pane, setPane] = useState<Pane>('profile');

  return (
    <>
      <PageHead title="Settings" sub="Your account, your sessions and how PainSense looks for you." />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
        <Card className="h-max p-2">
          <nav className="flex gap-0.5 lg:flex-col">
            {PANES.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setPane(entry.key)}
                className={cx(
                  'flex h-9 flex-1 items-center gap-2.5 rounded-[10px] px-2.5 text-[13px] font-medium transition-colors lg:flex-none',
                  pane === entry.key
                    ? 'bg-accent-wash text-accent-ink'
                    : 'text-soft hover:bg-sunken hover:text-ink',
                )}
              >
                <entry.icon
                  className={cx('h-4 w-4 shrink-0', pane === entry.key ? 'text-accent' : 'text-faint')}
                />
                {entry.label}
              </button>
            ))}
          </nav>
        </Card>

        <div className="space-y-4">
          {pane === 'profile' && user && <Profile user={user} />}

          {pane === 'security' && (
            <>
              <ChangePassword />
              <Sessions />
            </>
          )}

          {pane === 'appearance' && (
            <Card className="p-5">
              <CardHead title="Appearance" sub="How the workspace looks on this device" />
              <div className="mt-4 flex flex-wrap gap-3">
                {(['light', 'dark', 'system'] as const).map((value) => (
                  <ThemeCard
                    key={value}
                    value={value}
                    current={theme.preference}
                    onPick={theme.setPreference}
                  />
                ))}
              </div>
              <p className="mt-3 text-[11px] text-faint">
                Currently showing the {theme.resolved} theme
                {theme.preference === 'system' && ', following your operating system'}.
              </p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
};
