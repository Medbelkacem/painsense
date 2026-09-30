import { Activity, ArrowRight, ShieldCheck, Sparkles, Stethoscope } from 'lucide-react'
import { Link } from 'react-router-dom'

import { DISCLAIMER } from '@/components/Disclaimer'
import { InstallButton } from '@/components/InstallButton'
import { Lockup, Mark } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
import { LinkButton } from '@/components/ui/button'

const PILLARS = [
  {
    icon: Stethoscope,
    title: 'Signal',
    body: 'The clinician records the site, the character, the time course and the vital signs measured at the examination. The platform measures nothing itself.',
  },
  {
    icon: Activity,
    title: 'Clinical data',
    body: 'A questionnaire that narrows to the case in front of you. Chest pain opens different questions from a painful knee, and answering one can open another.',
  },
  {
    icon: Sparkles,
    title: 'PainSense',
    body: 'A trained model returns an intensity on a 0-10 scale with the interval it actually achieved on held-out data, or refuses when the record cannot support one.',
  },
  {
    icon: ShieldCheck,
    title: 'Insight',
    body: 'Every estimate comes with what moved it, the categories the picture fits, and rule-based alerts you can read line by line.',
  },
]

export function LandingPage() {
  return (
    <div className="min-h-dvh bg-canvas">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
          <Link to="/" aria-label="PainSense AI">
            <Lockup markClassName="size-7" wordClassName="text-lg" />
          </Link>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <ThemeToggle />
            <LinkButton to="/login" variant="ghost" size="sm">
              Log in
            </LinkButton>
            <LinkButton to="/register" variant="primary" size="sm">
              Sign up
            </LinkButton>
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-4 pt-12 pb-6 sm:px-6 lg:pt-20">
          <div className="grid items-center gap-10 lg:grid-cols-[1fr_1.05fr]">
            <div>
              <p className="text-[0.6875rem] font-semibold tracking-[0.18em] text-teal uppercase">
                Intelligent pain assessment platform
              </p>
              <h1 className="mt-3 text-4xl leading-[1.08] font-semibold text-ink sm:text-5xl">
                Understand pain.
                <br />
                Support better decisions.
              </h1>
              <p className="mt-5 max-w-xl text-[0.9375rem] leading-relaxed text-body">
                A clinician records what they found at the bedside. PainSense estimates the
                intensity, explains what moved that estimate, and puts the patient&rsquo;s own score
                beside it rather than in place of it.
              </p>

              <div className="mt-7 flex flex-wrap items-center gap-3">
                <LinkButton to="/register" variant="primary">
                  Create an account
                  <ArrowRight aria-hidden className="size-4" />
                </LinkButton>
                <LinkButton to="/login" variant="secondary">
                  Log in
                </LinkButton>
              </div>

              <div className="mt-4">
                <InstallButton />
              </div>
            </div>

            <div className="relative">
              <DeviceShowcase />
              <p className="mt-4 text-center text-xs text-faint">
                Interface shown with illustrative values.
              </p>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
          <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {PILLARS.map((pillar) => (
              <div key={pillar.title} className="bg-surface p-5">
                <pillar.icon aria-hidden className="size-5 text-teal" />
                <h2 className="mt-3 text-sm font-semibold text-ink">{pillar.title}</h2>
                <p className="mt-1.5 text-[0.8125rem] leading-relaxed text-body">{pillar.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-14 sm:px-6">
          <div className="grid gap-4 lg:grid-cols-2">
            <article className="rounded-xl border border-line bg-surface p-6">
              <h2 className="text-base font-semibold text-ink">
                The patient&rsquo;s own score is never a model input
              </h2>
              <p className="mt-2 text-[0.8125rem] leading-relaxed text-body">
                It has no field in the structure the model reads, so it cannot reach inference
                through an oversight. It is the reference the model is trained and measured
                against, and both numbers are printed side by side. Where they disagree, the
                platform says so instead of deciding which one is right.
              </p>
            </article>
            <article className="rounded-xl border border-line bg-surface p-6">
              <h2 className="text-base font-semibold text-ink">
                Records are sealed, and changes are provable
              </h2>
              <p className="mt-2 text-[0.8125rem] leading-relaxed text-body">
                Names are encrypted rather than stored in queryable columns. Every clinical record
                is hashed into an append-only ledger with a post-quantum signature, so an
                alteration is detectable rather than merely forbidden.
              </p>
            </article>
          </div>
        </section>
      </main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto max-w-6xl space-y-3 px-4 py-8 sm:px-6">
          <Mark className="size-6" />
          <p className="max-w-3xl text-xs leading-relaxed text-muted">{DISCLAIMER}</p>
          <p className="text-xs text-faint">
            Built for the ICAIMB 2026 PAIN SCORE challenge, University of Batna 2.
          </p>
        </div>
      </footer>
    </div>
  )
}

/**
 * A laptop and a phone showing the shape of the product.
 *
 * Drawn as markup rather than a screenshot so it stays sharp, follows the theme and does
 * not go stale when a screen changes. They sit side by side rather than overlapping, so
 * neither hides the other. The values are illustrative and the caption says so.
 */
function DeviceShowcase() {
  return (
    <div className="flex items-end gap-3 sm:gap-4">
      <div className="min-w-0 flex-1">
        <div className="rounded-t-lg border-4 border-b-0 border-brand-ink bg-brand-ink p-1 shadow-[var(--shadow-raised)]">
          <div className="overflow-hidden rounded bg-canvas">
            <MiniDashboard />
          </div>
        </div>
        <div className="h-2 rounded-b bg-line-strong" />
        <div className="mx-auto h-1 w-1/3 rounded-b bg-line-strong/60" />
      </div>

      <div className="hidden w-24 shrink-0 sm:block sm:w-28 lg:w-32">
        <div className="rounded-[1.3rem] border-[5px] border-brand-ink bg-brand-ink p-0.5 shadow-[var(--shadow-raised)]">
          <div className="overflow-hidden rounded-[1rem] bg-surface">
            <MiniPhone />
          </div>
        </div>
      </div>
    </div>
  )
}

const BARS = [
  { height: 26, colour: 'bg-band-none' },
  { height: 38, colour: 'bg-band-mild' },
  { height: 54, colour: 'bg-band-mild' },
  { height: 72, colour: 'bg-band-moderate' },
  { height: 88, colour: 'bg-band-moderate' },
  { height: 64, colour: 'bg-band-severe' },
  { height: 44, colour: 'bg-band-severe' },
  { height: 30, colour: 'bg-band-extreme' },
]

function MiniDashboard() {
  return (
    <div className="flex h-[14rem] text-[0.5rem] sm:h-[15.5rem]">
      <div className="hidden w-[4.5rem] shrink-0 border-r border-line bg-surface p-2 sm:block">
        <div className="flex items-center gap-1">
          <Mark className="size-3" />
          <span className="wordmark text-[0.5rem] text-brand-blue">PainSense</span>
        </div>
        <div className="mt-3 space-y-1">
          <div className="rounded bg-accent-soft px-1.5 py-1 text-accent">Dashboard</div>
          {['Patients', 'Assessments', 'Analytics'].map((item) => (
            <div key={item} className="px-1.5 py-1 text-faint">
              {item}
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0 flex-1 p-2.5">
        <p className="font-semibold text-ink">Good morning, Doctor.</p>
        <div className="mt-2 grid grid-cols-4 gap-1.5">
          {[
            ['Patients', '128'],
            ['Today', '14'],
            ['Active', '37'],
            ['To review', '5'],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-line bg-surface px-1.5 py-1">
              <p className="text-faint">{label}</p>
              <p className="text-[0.75rem] font-semibold text-ink tabular">{value}</p>
            </div>
          ))}
        </div>

        <div className="mt-2 rounded border border-line bg-surface p-2">
          <p className="text-muted">Pain overview</p>
          <div className="mt-1.5 flex h-16 items-end gap-1">
            {BARS.map((bar, index) => (
              <span
                key={index}
                className={`flex-1 rounded-t ${bar.colour}`}
                style={{ height: `${bar.height}%`, opacity: 0.85 }}
              />
            ))}
          </div>
        </div>

        <div className="mt-2 rounded border border-line bg-surface px-2 py-1.5">
          <div className="flex items-center justify-between">
            <span className="text-muted">Estimated pain</span>
            <span className="font-semibold text-violet tabular">7.2 / 10</span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-muted">Patient-reported</span>
            <span className="font-semibold text-ink tabular">4 / 10</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function MiniPhone() {
  return (
    <div className="flex h-[13.5rem] flex-col text-[0.4375rem] sm:h-[15rem]">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        <Mark className="size-2.5" />
        <span className="wordmark text-[0.4375rem] text-brand-blue">PainSense</span>
      </div>
      <div className="min-h-0 flex-1 space-y-1.5 p-2">
        <p className="text-faint">Step 2 of 7 &middot; Pain</p>
        <p className="text-[0.5625rem] font-semibold text-ink">Where is the pain?</p>
        <div className="grid grid-cols-2 gap-1">
          {['Head', 'Neck', 'Chest', 'Back', 'Abdomen', 'Limb'].map((site) => (
            <span
              key={site}
              className={
                site === 'Chest'
                  ? 'truncate rounded bg-accent px-1 py-1 text-center text-accent-contrast'
                  : 'truncate rounded border border-line px-1 py-1 text-center text-body'
              }
            >
              {site}
            </span>
          ))}
        </div>
        <p className="pt-0.5 text-faint">Pain intensity</p>
        <div className="flex gap-0.5">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((score) => (
            <span
              key={score}
              className={
                score === 6
                  ? 'flex-1 rounded bg-accent py-0.5 text-center text-accent-contrast'
                  : 'flex-1 rounded border border-line py-0.5 text-center text-body'
              }
            >
              {score}
            </span>
          ))}
        </div>
        <div className="rounded bg-accent px-2 py-1 text-center font-medium text-accent-contrast">
          Continue
        </div>
      </div>
      <div className="flex justify-around border-t border-line px-1 py-1 text-faint">
        {['Home', 'Patients', 'Assess', 'More'].map((tab) => (
          <span key={tab} className={tab === 'Assess' ? 'text-accent' : undefined}>
            {tab}
          </span>
        ))}
      </div>
    </div>
  )
}
