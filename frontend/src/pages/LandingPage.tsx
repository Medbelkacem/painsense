import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight, BrainCircuit, ClipboardList, Gauge as GaugeIcon, LineChart, Lock,
  Moon, ScrollText, ShieldCheck, Sun,
} from 'lucide-react';
import { Logo } from '../ui/Logo';
import { Button, IconButton } from '../ui/Button';
import { Card } from '../ui/Card';
import { Pill, Tile } from '../ui/Pill';
import { BandBars, Sparkline, Waveform } from '../ui/charts';
import { NrsScale } from '../ui/NrsScale';
import { nrsDistribution, patients } from '../demo/cohort';
import { useTheme } from '../theme';

const PILLARS = [
  {
    icon: ClipboardList,
    title: 'Structured assessment',
    body: 'A seven-step flow whose questions change with the region the patient points to, so nobody answers about jaw radiation for a knee.',
  },
  {
    icon: BrainCircuit,
    title: 'An estimate that explains itself',
    body: 'Every score comes with the interval around it and the fields that moved it. Where the model and the patient disagree, the patient is the reference.',
  },
  {
    icon: LineChart,
    title: 'Trends worth acting on',
    body: 'Pain history per patient and across the cohort, with the model line drawn against the reported one rather than instead of it.',
  },
  {
    icon: ShieldCheck,
    title: 'Evidence it was not altered',
    body: 'Assessments, predictions and exports are hashed into a linked chain. Every read is attributed to an account.',
  },
];

const FLOW = [
  { step: '01', title: 'Signal', note: 'The patient reports where it hurts and how much.' },
  { step: '02', title: 'Clinical data', note: 'Symptoms, vitals, medication and context are recorded.' },
  { step: '03', title: 'PainSense', note: 'Model and rules produce an estimate with an interval.' },
  { step: '04', title: 'Insight', note: 'The clinician reviews, adjusts and signs.' },
];

export const LandingPage: React.FC = () => {
  const theme = useTheme();
  const counts = nrsDistribution();

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="sticky top-0 z-40 border-b border-hairline bg-surface/85 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-5">
          <Logo size="md" />
          <nav className="ml-4 hidden items-center gap-6 text-[13px] font-medium text-soft md:flex">
            <a href="#what" className="transition-colors hover:text-ink">
              What it does
            </a>
            <a href="#flow" className="transition-colors hover:text-ink">
              How it works
            </a>
            <a href="#trust" className="transition-colors hover:text-ink">
              Trust
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <IconButton
              label={theme.resolved === 'dark' ? 'Switch to light' : 'Switch to dark'}
              onClick={theme.toggle}
            >
              {theme.resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </IconButton>
            <Link to="/login">
              <Button>Sign in</Button>
            </Link>
            <Link to="/dashboard" className="hidden sm:block">
              <Button variant="primary">
                Open the workspace
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto grid w-full max-w-6xl gap-10 px-5 py-16 lg:grid-cols-[1.05fr_1fr] lg:py-24">
          <div className="max-w-xl">
            <Pill tone="teal" dot>
              Intelligent pain assessment platform
            </Pill>
            <h1 className="mt-5 text-[clamp(2.4rem,5vw,3.6rem)] leading-[1.06] font-semibold tracking-[-0.035em] text-ink">
              Understand pain.
              <br />
              Support better decisions.
            </h1>
            <p className="mt-5 max-w-lg text-[15px] leading-relaxed text-soft">
              PainSense records what a patient reports, adds the clinical context around it, and
              returns an estimate with the uncertainty still attached. It is decision support — the
              clinician signs, and the patient's own number stays the reference.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/dashboard">
                <Button variant="primary" size="lg">
                  Open the workspace
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
              <Link to="/login">
                <Button size="lg">Sign in</Button>
              </Link>
            </div>
            <p className="mt-6 flex items-center gap-2 text-[11.5px] text-faint">
              <Lock className="h-3.5 w-3.5" />
              Demonstration workspace running on synthetic data · clinical decision support only
            </p>
          </div>

          {/* A live fragment of the product rather than a screenshot — it is the same
              components the workspace uses, so it can never go stale. */}
          <div className="relative">
            <Card className="overflow-hidden p-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[13px] font-semibold text-ink">Pain overview</p>
                  <p className="text-[11px] text-mute">Patient-reported NRS · last 30 days</p>
                </div>
                <Pill tone="violet" size="xs" dot>
                  Synthetic
                </Pill>
              </div>
              <BandBars counts={counts} className="mt-5" showLabels={false} />
              <div className="mt-5 grid grid-cols-3 gap-3 border-t border-hairline pt-4">
                {[
                  ['Patients', String(patients.length)],
                  ['Mean NRS', '4.2'],
                  ['Mean |AI − NRS|', '0.62'],
                ].map(([label, value]) => (
                  <div key={label}>
                    <p className="text-[10px] text-faint">{label}</p>
                    <p className="mt-0.5 text-[18px] font-semibold text-ink tabular-nums">{value}</p>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="absolute -bottom-8 -left-4 hidden w-64 p-4 sm:block">
              <p className="text-[11px] text-mute">Reported intensity</p>
              <div className="mt-2">
                <NrsScale value={6} ghost={6.4} size="sm" />
              </div>
            </Card>
          </div>
        </section>

        <section id="what" className="border-y border-hairline bg-surface">
          <div className="mx-auto w-full max-w-6xl px-5 py-16">
            <p className="eyebrow">What it does</p>
            <h2 className="mt-2 max-w-2xl text-[30px] leading-tight font-semibold tracking-[-0.03em]">
              Four things, each of which a clinician can check.
            </h2>
            <div className="mt-10 grid gap-5 sm:grid-cols-2">
              {PILLARS.map((pillar) => (
                <div key={pillar.title} className="flex gap-4">
                  <Tile tone="accent" className="h-10 w-10 shrink-0 rounded-xl">
                    <pillar.icon className="h-4.5 w-4.5" />
                  </Tile>
                  <div>
                    <h3 className="text-[15px] font-semibold text-ink">{pillar.title}</h3>
                    <p className="mt-1.5 text-[13px] leading-relaxed text-soft">{pillar.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="flow" className="mx-auto w-full max-w-6xl px-5 py-16">
          <p className="eyebrow">How it works</p>
          <h2 className="mt-2 max-w-2xl text-[30px] leading-tight font-semibold tracking-[-0.03em]">
            From what the patient says to something you can sign.
          </h2>
          <ol className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {FLOW.map((entry, index) => (
              <li key={entry.step}>
                <div
                  className="h-0.5 w-full rounded-full"
                  style={{
                    background:
                      index === FLOW.length - 1 ? 'var(--brand-teal)' : 'var(--hairline-strong)',
                  }}
                />
                <p className="mt-3 text-[11px] text-faint">{entry.step}</p>
                <h3 className="mt-1 text-[15px] font-semibold text-ink">{entry.title}</h3>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-mute">{entry.note}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="trust" className="border-t border-hairline bg-[#0b1b33] text-white">
          <div className="relative mx-auto w-full max-w-6xl overflow-hidden px-5 py-20">
            <Waveform className="absolute inset-x-0 top-10 h-32 opacity-25" />
            <div className="relative z-10 max-w-2xl">
              <p className="text-[11px] font-semibold tracking-[0.18em] text-teal uppercase">
                Trust
              </p>
              <h2 className="mt-4 text-[32px] leading-tight font-semibold tracking-[-0.03em]">
                A tool that shows its working.
              </h2>
              <p className="mt-4 text-[14px] leading-relaxed text-white/65">
                The serving model is trained on synthetic data and says so on every screen that uses
                it. Estimates carry intervals. Records are hashed into a linked chain so an
                after-the-fact edit is detectable. Nothing here is a diagnosis, and the product never
                presents itself as one.
              </p>
              <div className="mt-10 grid gap-8 sm:grid-cols-3">
                {[
                  { icon: GaugeIcon, title: 'Uncertainty shown', note: 'Intervals widen when answers are missing.' },
                  { icon: ScrollText, title: 'Append-only audit', note: 'Every read, prediction and export attributed.' },
                  { icon: Lock, title: 'Local processing', note: 'Patient data stays on the deployment.' },
                ].map((item) => (
                  <div key={item.title}>
                    <item.icon className="h-5 w-5 text-teal" />
                    <h3 className="mt-3 text-[14px] font-semibold">{item.title}</h3>
                    <p className="mt-1 text-[12px] leading-relaxed text-white/55">{item.note}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto w-full max-w-6xl px-5 py-16">
          <Card className="flex flex-wrap items-center justify-between gap-6 p-8">
            <div className="max-w-md">
              <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-ink">
                Open the demonstration workspace
              </h2>
              <p className="mt-2 text-[13px] text-soft">
                128 synthetic patients, 137 assessments and the full assessment flow — no account
                needed.
              </p>
            </div>
            <div className="flex items-center gap-4">
              <div className="hidden w-32 sm:block">
                <Sparkline values={[3, 4, 3.6, 5, 4.4, 5.8, 4.9]} tone="var(--brand-teal)" />
              </div>
              <Link to="/dashboard">
                <Button variant="primary" size="lg">
                  Open workspace
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </Card>
        </section>
      </main>

      <footer className="border-t border-hairline bg-surface">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-[11.5px] text-faint">
          <Logo size="sm" />
          <span>Clinical decision support only · not a diagnosis · synthetic demonstration data</span>
          <span>v1.0 · build 2026.09</span>
        </div>
      </footer>
    </div>
  );
};
