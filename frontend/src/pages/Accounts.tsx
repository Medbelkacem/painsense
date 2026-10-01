import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Lock, LockOpen, MoreHorizontal, Plus, Search, ShieldOff, UserPlus, Users, X,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type { Page, PatientSummary, Role, User } from '../api/types';
import { Card, EmptyState, PageHead } from '../ui/Card';
import { Button, IconButton } from '../ui/Button';
import { Pill, Tile } from '../ui/Pill';
import { SearchField, TextField } from '../ui/Field';
import { Menu, Select } from '../ui/Dropdown';
import { DataTable, type Column } from '../ui/Table';
import { useSession } from '../auth/session';
import { cx } from '../lib/cx';
import { initials, whenShort } from '../lib/format';
import { ROLE_LABEL, ROLE_TONE } from './Settings';

type Profession = User['profession'];

const PROFESSION_LABEL: Record<Profession, string> = {
  DOCTOR: 'Doctor',
  NURSE: 'Nurse',
  RESIDENT: 'Resident',
  OTHER: 'Other',
};

const MIN_PASSWORD = 12;

interface RoleOption {
  code: Role;
  label: string;
}

const locked = (user: User) =>
  Boolean(user.locked_until) && new Date(user.locked_until as string).getTime() > Date.now();

export const Accounts: React.FC = () => {
  const { user: me } = useSession();

  const [users, setUsers] = useState<User[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  const roles = useQuery<RoleOption[]>('/api/users/roles');

  // Not useQuery: the one thing this page has to tell apart is a 403, and the hook
  // flattens every failure to its message.
  const load = useCallback(async () => {
    try {
      setUsers(await request<User[]>('/api/users'));
      setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) setForbidden(true);
      else setError(cause instanceof ApiError ? cause.message : 'Could not reach the server');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const roleOptions = useMemo(
    () =>
      (roles.data ?? (Object.keys(ROLE_LABEL) as Role[]).map((code) => ({
        code,
        label: ROLE_LABEL[code],
      }))).map((role) => ({ value: role.code, label: role.label })),
    [roles.data],
  );

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return users ?? [];
    return (users ?? []).filter((user) =>
      `${user.display_name} ${user.email} ${user.clinic_name ?? ''}`.toLowerCase().includes(needle),
    );
  }, [users, query]);

  const act = async (user: User, path: string, options: { method: string; body?: unknown }) => {
    setPending(user.id);
    setError(null);
    try {
      await request<unknown>(path, options);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The change could not be applied.');
    } finally {
      setPending(null);
    }
  };

  const patch = (user: User, body: Partial<User>) =>
    act(user, `/api/users/${user.id}`, { method: 'PATCH', body });

  const changeRole = (user: User, role: Role) => {
    // Leaving the patient role drops the record link; joining it needs one the row
    // does not have, so that case is left to the server's own message.
    const body: Partial<User> = { role };
    if (user.role === 'PATIENT' && role !== 'PATIENT') body.patient_id = null;
    return patch(user, body);
  };

  const columns: Column<User>[] = [
    {
      key: 'who',
      header: 'Account',
      cell: (user) => (
        <div className="flex items-center gap-2.5">
          <Tile tone={user.is_active ? ROLE_TONE[user.role] : 'neutral'}>
            {initials(user.display_name)}
          </Tile>
          <div className="min-w-0">
            <p className={cx('truncate font-semibold', user.is_active ? 'text-ink' : 'text-mute')}>
              {user.display_name}
              {me?.id === user.id && <span className="ml-1.5 text-[11px] font-normal text-faint">you</span>}
            </p>
            <p className="truncate text-[11px] text-faint">{user.email}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      cell: (user) =>
        me?.id === user.id ? (
          <Pill tone={ROLE_TONE[user.role]} size="xs">
            {ROLE_LABEL[user.role]}
          </Pill>
        ) : (
          <Select
            label="Role"
            size="sm"
            clearable={false}
            options={roleOptions}
            value={user.role}
            onChange={(value) => {
              if (value && value !== user.role) void changeRole(user, value);
            }}
          />
        ),
    },
    {
      key: 'profession',
      header: 'Profession',
      hideBelow: 'md',
      cell: (user) => <span className="text-soft">{PROFESSION_LABEL[user.profession]}</span>,
    },
    {
      key: 'state',
      header: 'State',
      cell: (user) =>
        !user.is_active ? (
          <Pill tone="neutral" size="xs" dot>
            disabled
          </Pill>
        ) : locked(user) ? (
          <Pill tone="danger" size="xs" icon={<Lock className="h-2.5 w-2.5" />}>
            locked until {whenShort(new Date(user.locked_until as string))}
          </Pill>
        ) : (
          <Pill tone="ok" size="xs" dot>
            active
          </Pill>
        ),
    },
    {
      key: 'seen',
      header: 'Last sign-in',
      hideBelow: 'md',
      cell: (user) => (
        <span className="text-mute">
          {user.last_login_at ? whenShort(new Date(user.last_login_at)) : 'Never'}
        </span>
      ),
    },
    {
      key: 'patient',
      header: 'Patient record',
      hideBelow: 'lg',
      cell: (user) => (
        <span className="text-[12px] text-mute">
          {user.patient_code ?? (user.patient_id ? user.patient_id.slice(0, 8) : '—')}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (user) =>
        me?.id === user.id ? null : (
          <Menu
            width="w-56"
            trigger={({ toggle }) => (
              <IconButton
                label="Account actions"
                className="ml-auto h-8 w-8"
                disabled={pending === user.id}
                onClick={toggle}
              >
                <MoreHorizontal className="h-4 w-4" />
              </IconButton>
            )}
            entries={[
              locked(user)
                ? {
                    label: 'Unlock',
                    icon: <LockOpen className="h-3.5 w-3.5" />,
                    onSelect: () => void act(user, `/api/users/${user.id}/unlock`, { method: 'POST' }),
                  }
                : null,
              {
                label: 'Revoke sessions',
                icon: <ShieldOff className="h-3.5 w-3.5" />,
                hint: 'signs them out',
                onSelect: () =>
                  void act(user, `/api/users/${user.id}/revoke-sessions`, { method: 'POST' }),
              },
              null,
              user.is_active
                ? {
                    label: 'Disable account',
                    tone: 'danger',
                    icon: <X className="h-3.5 w-3.5" />,
                    onSelect: () => void patch(user, { is_active: false }),
                  }
                : {
                    label: 'Enable account',
                    icon: <LockOpen className="h-3.5 w-3.5" />,
                    onSelect: () => void patch(user, { is_active: true }),
                  },
            ]}
          />
        ),
    },
  ];

  if (forbidden) {
    return (
      <>
        <PageHead title="Accounts" sub="Who can sign in, and as what." />
        <Card>
          <EmptyState
            icon={<Lock className="h-5 w-5" />}
            title="Administrators only"
            sub="Your account can see its own settings, but not the list of accounts in this workspace."
          />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="Accounts"
        sub="Who can sign in, and as what."
        action={
          <Button
            variant="primary"
            icon={<UserPlus className="h-4 w-4" />}
            onClick={() => setCreating(true)}
          >
            New account
          </Button>
        }
      />

      {error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">{error}</Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <SearchField
            icon={<Search className="h-4 w-4" />}
            value={query}
            placeholder="Name, email or clinic…"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-[14rem] sm:w-80"
          />
          <span className="ml-auto text-[12px] text-faint">
            {loading ? 'Loading…' : `${rows.length} of ${users?.length ?? 0}`}
          </span>
        </div>

        <div className="mt-4">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(user) => user.id}
            empty={
              <EmptyState
                icon={<Users className="h-5 w-5" />}
                title={loading ? 'Loading…' : query ? 'Nothing matches' : 'No account yet'}
                sub={query ? 'Try a shorter name, or the email address.' : undefined}
              />
            }
          />
        </div>
      </Card>

      {creating && (
        <NewAccount
          roles={roleOptions}
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
    </>
  );
};

/** Finds the patient record a PATIENT account is allowed to read. */
const PatientPicker: React.FC<{
  value: PatientSummary | null;
  onChange: (patient: PatientSummary | null) => void;
}> = ({ value, onChange }) => {
  const [query, setQuery] = useState('');
  const [needle, setNeedle] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setNeedle(query.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const path = useMemo(() => {
    const search = new URLSearchParams({ limit: '25' });
    if (needle) search.set('search', needle);
    return `/api/patients?${search}`;
  }, [needle]);

  const { data, error, loading } = useQuery<Page<PatientSummary>>(value ? null : path);

  if (value) {
    return (
      <div className="flex items-center gap-2.5 rounded-[10px] border border-accent-edge bg-accent-wash px-3 py-2">
        <Tile tone="accent">{value.code.slice(-3)}</Tile>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium text-ink">{value.display_name}</p>
          <p className="truncate text-[11px] text-mute">{value.code}</p>
        </div>
        <button
          type="button"
          onClick={() => onChange(null)}
          aria-label="Choose another patient"
          className="rounded-lg p-1.5 text-faint hover:bg-surface hover:text-ink"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="rounded-[10px] border border-hairline">
      <div className="border-b border-hairline p-2">
        <SearchField
          autoFocus
          icon={<Search className="h-4 w-4" />}
          value={query}
          placeholder="Name, code or ward…"
          onChange={(event) => setQuery(event.target.value)}
          className="border-0 bg-transparent"
        />
      </div>
      <div role="listbox" aria-label="Patient" className="max-h-56 overflow-y-auto p-1.5">
        {error && <p className="px-2.5 py-3 text-xs text-danger">{error}</p>}
        {!error && items.length === 0 && (
          <p className="px-2.5 py-3 text-center text-xs text-faint">
            {loading ? 'Loading…' : 'No patient matches'}
          </p>
        )}
        {items.map((patient) => (
          <button
            key={patient.id}
            type="button"
            role="option"
            aria-selected={false}
            onClick={() => onChange(patient)}
            className="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] text-soft hover:bg-sunken hover:text-ink"
          >
            <span className="min-w-0 flex-1 truncate">{patient.display_name}</span>
            <span className="shrink-0 text-[11px] text-faint">{patient.code}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

const NewAccount: React.FC<{
  roles: readonly { value: Role; label: string }[];
  onClose: () => void;
  onCreated: (user: User) => void;
}> = ({ roles, onClose, onCreated }) => {
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<Role>('DOCTOR');
  const [profession, setProfession] = useState<Profession>('DOCTOR');
  const [clinic, setClinic] = useState('');
  const [phone, setPhone] = useState('');
  const [registration, setRegistration] = useState('');
  const [speciality, setSpeciality] = useState('');
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    try {
      onCreated(
        await request<User>('/api/users', {
          method: 'POST',
          body: {
            email: email.trim(),
            display_name: displayName.trim(),
            password,
            role,
            profession,
            clinic_name: clinic.trim() || undefined,
            phone: phone.trim() || undefined,
            registration_number: registration.trim() || undefined,
            speciality: speciality.trim() || undefined,
            patient_id: role === 'PATIENT' ? patient?.id : undefined,
          },
        }),
      );
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The account could not be created.');
      setBusy(false);
    }
  }, [
    clinic, displayName, email, onCreated, password, patient, phone, profession, registration,
    role, speciality,
  ]);

  const complete =
    email.includes('@') &&
    displayName.trim().length >= 2 &&
    password.length >= MIN_PASSWORD &&
    (role !== 'PATIENT' || patient !== null);

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-[#0b1b33]/40 px-4 py-[8vh] backdrop-blur-[2px]"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-label="New account"
        className="w-full max-w-2xl rounded-2xl border border-hairline bg-surface p-5 shadow-pop"
      >
        <div className="flex items-start justify-between gap-4 pb-4">
          <div>
            <h2 className="text-[17px] font-semibold text-ink">New account</h2>
            <p className="mt-1 text-[12px] text-mute">
              Hand the password over in person. The holder can change it from their own settings.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-faint hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {failure && (
          <p className="mb-4 rounded-[10px] border border-danger/25 bg-danger/8 px-3 py-2 text-[12px] text-danger">
            {failure}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            label="Display name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
          <TextField
            label="Email"
            type="email"
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <TextField
            label="Initial password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={
              password.length > 0 && password.length < MIN_PASSWORD
                ? `${MIN_PASSWORD - password.length} more`
                : null
            }
            hint={`At least ${MIN_PASSWORD} characters`}
          />
          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-soft">Role</span>
            <Select
              label="Role"
              clearable={false}
              className="w-full [&>button]:w-full"
              options={roles}
              value={role}
              onChange={(value) => {
                if (value) setRole(value);
              }}
            />
          </div>
          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-soft">Profession</span>
            <Select
              label="Profession"
              clearable={false}
              className="w-full [&>button]:w-full"
              options={(Object.keys(PROFESSION_LABEL) as Profession[]).map((value) => ({
                value,
                label: PROFESSION_LABEL[value],
              }))}
              value={profession}
              onChange={(value) => {
                if (value) setProfession(value);
              }}
            />
          </div>
          <TextField label="Clinic" value={clinic} onChange={(event) => setClinic(event.target.value)} />
          <TextField label="Telephone" value={phone} onChange={(event) => setPhone(event.target.value)} />
          <TextField
            label="Registration number"
            value={registration}
            onChange={(event) => setRegistration(event.target.value)}
          />
          <TextField
            label="Speciality"
            value={speciality}
            onChange={(event) => setSpeciality(event.target.value)}
            className="sm:col-span-2"
          />
        </div>

        {role === 'PATIENT' && (
          <div className="mt-4 border-t border-hairline pt-4">
            <p className="text-xs font-medium text-soft">Patient record</p>
            <p className="mt-0.5 mb-2 text-[11px] leading-relaxed text-faint">
              A patient account reads exactly one record: this one.
            </p>
            <PatientPicker value={patient} onChange={setPatient} />
          </div>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            disabled={!complete || busy}
            onClick={() => void submit()}
          >
            {busy ? 'Creating…' : 'Create account'}
          </Button>
        </div>
      </div>
    </div>
  );
};
