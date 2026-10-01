import React, { useState } from 'react';
import {
  Bell, Building2, Check, Eye, Monitor, Moon, Palette, ShieldCheck, Sparkles, Sun, UserRound,
} from 'lucide-react';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill } from '../ui/Pill';
import { Select } from '../ui/Dropdown';
import { TextField, ToggleRow } from '../ui/Field';
import { useTheme, type ThemePreference } from '../theme';
import { useSession } from '../auth/session';
import { cx } from '../lib/cx';

const PANES = [
  { key: 'profile', label: 'Profile', icon: UserRound },
  { key: 'organisation', label: 'Organisation', icon: Building2 },
  { key: 'security', label: 'Security', icon: ShieldCheck },
  { key: 'appearance', label: 'Appearance', icon: Palette },
  { key: 'privacy', label: 'Privacy', icon: Eye },
  { key: 'notifications', label: 'Notifications', icon: Bell },
  { key: 'ai', label: 'AI preferences', icon: Sparkles },
] as const;

type Pane = (typeof PANES)[number]['key'];

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

export const Settings: React.FC = () => {
  const theme = useTheme();
  const { user } = useSession();
  const [pane, setPane] = useState<Pane>('appearance');

  const [density, setDensity] = useState(false);
  const [motion, setMotion] = useState(false);
  const [showAi, setShowAi] = useState(true);
  const [aiFirst, setAiFirst] = useState(false);
  const [askFeedback, setAskFeedback] = useState(true);
  const [emailDigest, setEmailDigest] = useState(true);
  const [flagAlerts, setFlagAlerts] = useState(true);
  const [language, setLanguage] = useState<string | null>('en-GB');

  return (
    <>
      <PageHead
        title="Settings"
        sub="Account, organisation and how PainSense behaves for you."
        action={<Button variant="primary">Save changes</Button>}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_1fr]">
        <Card className="h-max p-2">
          <nav className="space-y-0.5">
            {PANES.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setPane(entry.key)}
                className={cx(
                  'flex h-9 w-full items-center gap-2.5 rounded-[10px] px-2.5 text-[13px] font-medium transition-colors',
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
          {pane === 'appearance' && (
            <>
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

              <Card className="px-5 py-2">
                <ToggleRow
                  title="Compact density"
                  sub="Tighter rows in tables and lists — more records per screen."
                  checked={density}
                  onChange={setDensity}
                />
                <div className="h-px bg-hairline" />
                <ToggleRow
                  title="Reduce motion"
                  sub="Removes chart draw-ins and panel transitions."
                  checked={motion}
                  onChange={setMotion}
                />
                <div className="h-px bg-hairline" />
                <div className="flex items-center justify-between gap-6 py-3">
                  <div>
                    <p className="text-[13px] font-medium text-ink">Language and formats</p>
                    <p className="mt-0.5 text-xs text-mute">Dates, numbers and the interface language.</p>
                  </div>
                  <Select
                    label="Locale"
                    clearable={false}
                    options={[
                      { value: 'en-GB', label: 'English (UK)' },
                      { value: 'fr-FR', label: 'Français' },
                      { value: 'ar-DZ', label: 'العربية' },
                    ]}
                    value={language}
                    onChange={setLanguage}
                    align="end"
                  />
                </div>
              </Card>
            </>
          )}

          {pane === 'ai' && (
            <Card className="px-5 py-2">
              <div className="py-3">
                <CardHead
                  title="AI preferences"
                  sub="What the model is allowed to show you, and when."
                />
              </div>
              <div className="h-px bg-hairline" />
              <ToggleRow
                title="Show AI estimates"
                sub="Display the model's number alongside the patient's own report."
                checked={showAi}
                onChange={setShowAi}
              />
              <div className="h-px bg-hairline" />
              <ToggleRow
                title="Open assessments on the AI step"
                sub="Skip straight to the analysis when a draft already has an intensity."
                checked={aiFirst}
                onChange={setAiFirst}
              />
              <div className="h-px bg-hairline" />
              <ToggleRow
                title="Ask for feedback on sign-off"
                sub="One question after signing: was the estimate useful? Feeds the evaluation set."
                checked={askFeedback}
                onChange={setAskFeedback}
              />
              <div className="px-0 py-4">
                <div className="rounded-xl border border-hairline bg-sunken p-3">
                  <p className="text-[12px] leading-relaxed text-soft">
                    Turning estimates off hides them from your view only. They are still computed and
                    recorded, because the audit trail has to show what the system produced at the time
                    of the decision.
                  </p>
                </div>
              </div>
            </Card>
          )}

          {pane === 'notifications' && (
            <Card className="px-5 py-2">
              <div className="py-3">
                <CardHead title="Notifications" sub="What reaches you outside the workspace." />
              </div>
              <div className="h-px bg-hairline" />
              <ToggleRow
                title="Red-flag alerts"
                sub="Immediate notification when a rule fires on one of your patients."
                checked={flagAlerts}
                onChange={setFlagAlerts}
              />
              <div className="h-px bg-hairline" />
              <ToggleRow
                title="Daily digest"
                sub="One email each morning with the review queue."
                checked={emailDigest}
                onChange={setEmailDigest}
              />
            </Card>
          )}

          {pane === 'profile' && (
            <Card className="p-5">
              <CardHead title="Profile" sub="Shown on reports and in the audit trail." />
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TextField label="Display name" defaultValue={user?.display_name ?? 'Dr. Ahmed B.'} />
                <TextField label="Email" defaultValue={user?.email ?? 'ahmed.b@clinic-demo.dz'} />
                <TextField label="Speciality" defaultValue={user?.speciality ?? 'Internal medicine'} />
                <TextField label="Registration number" defaultValue="DZ-MED-20581" />
              </div>
            </Card>
          )}

          {pane === 'organisation' && (
            <Card className="p-5">
              <CardHead title="Organisation" sub="Applies to everyone in this workspace." />
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TextField label="Clinic name" defaultValue={user?.clinic_name ?? 'Clinic Demo · Batna'} />
                <TextField label="Time zone" defaultValue="Africa/Algiers (GMT+1)" />
                <TextField label="Record retention" defaultValue="7 years" />
                <TextField label="Data residency" defaultValue="On-premises" />
              </div>
            </Card>
          )}

          {pane === 'security' && (
            <Card className="p-5">
              <CardHead title="Security" sub="Session and sign-in controls for your account." />
              <ul className="mt-4 space-y-3">
                {[
                  ['Two-factor authentication', 'Enabled · authenticator app', 'ok'],
                  ['Session timeout', '30 minutes of inactivity', 'neutral'],
                  ['Active sessions', '2 devices', 'neutral'],
                  ['Last password change', '18 days ago', 'neutral'],
                ].map(([label, value, tone]) => (
                  <li key={label} className="flex items-center justify-between gap-4 border-b border-hairline pb-2.5">
                    <div>
                      <p className="text-[13px] font-medium text-ink">{label}</p>
                      <p className="mt-0.5 text-[11.5px] text-mute">{value}</p>
                    </div>
                    <Pill tone={tone as 'ok' | 'neutral'} size="xs">
                      {tone === 'ok' ? 'Active' : 'Manage'}
                    </Pill>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {pane === 'privacy' && (
            <Card className="p-5">
              <CardHead title="Privacy" sub="What leaves this workspace." />
              <ul className="mt-4 space-y-3 text-[12.5px] leading-relaxed text-soft">
                <li className="rounded-xl border border-hairline bg-sunken p-3">
                  Patient data is processed on this deployment. No record is sent to a third party,
                  and the model runs locally.
                </li>
                <li className="rounded-xl border border-hairline bg-sunken p-3">
                  Exports carry the synthetic-data notice. Removing it from a generated document is a
                  deliberate act and is recorded in the audit log.
                </li>
                <li className="rounded-xl border border-hairline bg-sunken p-3">
                  Every read of a patient record is attributed to an account. There is no anonymous
                  access path.
                </li>
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
};
