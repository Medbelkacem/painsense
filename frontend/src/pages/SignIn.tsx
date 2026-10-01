import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Lock, Moon, ShieldCheck, Sun, UserRound } from 'lucide-react';
import { Logo } from '../ui/Logo';
import { Button, IconButton } from '../ui/Button';
import { TextField } from '../ui/Field';
import { Waveform } from '../ui/charts';
import { useSession } from '../auth/session';
import { useTheme } from '../theme';
import { ApiError } from '../api/client';
import { DISCLAIMER } from '../lib/clinical';

const PIPELINE = [
  { step: '01', title: 'Signal', note: 'Pain reported' },
  { step: '02', title: 'Clinical data', note: 'Symptoms, vitals' },
  { step: '03', title: 'PainSense', note: 'Model + rules' },
  { step: '04', title: 'Insight', note: 'Explained estimate' },
];

export const SignIn: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { signIn } = useSession();
  const theme = useTheme();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const returnTo = (location.state as { from?: string } | null)?.from ?? null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await signIn(email, password);
      navigate(returnTo ?? (user.role === 'PATIENT' ? '/my-record' : '/dashboard'), {
        replace: true,
      });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not reach the server. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh bg-surface lg:grid-cols-2">
      {/* The brand panel is fixed navy in both themes: it is the one surface in the
          product that carries the identity rather than the workspace chrome. */}
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-[#0b1b33] p-10 lg:flex">
        <Logo variant="light" size="md" showAi={false} />

        <div className="relative z-10 max-w-md">
          <p className="text-[11px] font-semibold tracking-[0.18em] text-teal uppercase">
            Intelligent pain assessment platform
          </p>
          <h1 className="mt-4 text-[44px] leading-[1.08] font-semibold tracking-[-0.03em] text-white">
            Understand pain.
            <br />
            Support better decisions.
          </h1>
        </div>

        <Waveform className="absolute inset-x-0 bottom-44 h-28 opacity-70" />

        <div className="relative z-10">
          <ol className="grid grid-cols-4 gap-4">
            {PIPELINE.map((entry, index) => (
              <li key={entry.step} className="border-t pt-3" style={{ borderColor: index === 3 ? 'var(--brand-teal)' : 'rgba(255,255,255,0.14)' }}>
                <p className="text-[10px] text-white/40">{entry.step}</p>
                <p className="mt-1 text-[13px] font-semibold text-white">{entry.title}</p>
                <p className="mt-0.5 text-[11px] text-white/50">{entry.note}</p>
              </li>
            ))}
          </ol>
          <p className="mt-8 flex items-center gap-2 text-[11px] text-white/45">
            <ShieldCheck className="h-3.5 w-3.5" />
            Secure clinical workspace · every access is audited
          </p>
        </div>
      </aside>

      <main className="flex flex-col p-6 sm:p-10">
        <div className="flex items-center justify-between">
          <div className="lg:hidden">
            <Logo size="sm" />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <IconButton
              label={theme.resolved === 'dark' ? 'Switch to light' : 'Switch to dark'}
              onClick={theme.toggle}
            >
              {theme.resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </IconButton>
          </div>
        </div>

        <form onSubmit={submit} className="mx-auto my-auto w-full max-w-[380px] py-10">
          <h2 className="text-[26px] font-semibold text-ink">Sign in</h2>
          <p className="mt-1 text-[13px] text-mute">Use your clinical workspace account.</p>

          <div className="mt-7 space-y-4">
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              required
              icon={<UserRound className="h-4 w-4" />}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <TextField
              label="Password"
              type={reveal ? 'text' : 'password'}
              autoComplete="current-password"
              required
              icon={<Lock className="h-4 w-4" />}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              trailing={
                <button
                  type="button"
                  onClick={() => setReveal((value) => !value)}
                  aria-label={reveal ? 'Hide password' : 'Show password'}
                  className="shrink-0 text-faint transition-colors hover:text-ink"
                >
                  {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              }
            />

            {error && (
              <p
                role="alert"
                className="rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[12.5px] text-danger"
              >
                {error}
              </p>
            )}

            <Button type="submit" variant="primary" size="lg" disabled={busy} className="w-full">
              {busy ? 'Signing in…' : 'Sign in'}
            </Button>
            <p className="text-[11.5px] leading-relaxed text-faint">
              Accounts are created by the administrator. A forgotten password is reset by them
              as well.
            </p>
          </div>
        </form>

        <p className="text-[11px] text-faint">{DISCLAIMER}</p>
      </main>
    </div>
  );
};
