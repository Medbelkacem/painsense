import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { DISCLAIMER } from '@/components/Disclaimer'
import { Lockup } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'

const PILLARS = [
  ['01', 'Signal', 'Recorded at the bedside'],
  ['02', 'Clinical data', 'Symptoms, vitals, history'],
  ['03', 'PainSense', 'Model estimate'],
  ['04', 'Insight', 'Explained, with its interval'],
]

/**
 * The split screen the brand uses for sign-in and sign-up.
 *
 * The dark half carries the promise and the four steps; the light half carries the form.
 * On a phone the dark half collapses to a header so the form is the first thing in reach.
 */
export function AuthPanel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[1.05fr_1fr]">
      <section className="relative flex flex-col justify-between overflow-hidden bg-brand-ink px-6 py-8 text-white sm:px-10 lg:py-12">
        <Link to="/" aria-label="PainSense AI">
          <Lockup tone="reversed" markClassName="size-7" wordClassName="text-lg" />
        </Link>

        <div className="relative z-10 my-10 lg:my-0">
          <p className="text-[0.6875rem] font-semibold tracking-[0.18em] text-brand-teal uppercase">
            Intelligent pain assessment platform
          </p>
          <h2 className="mt-4 max-w-md text-3xl leading-[1.12] font-semibold sm:text-4xl">
            Understand pain.
            <br />
            Support better decisions.
          </h2>
        </div>

        <Waveform />

        <div className="relative z-10 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          {PILLARS.map(([index, name, note]) => (
            <div key={name} className="border-t border-white/15 pt-2.5">
              <p className="text-[0.625rem] text-white/45 tabular">{index}</p>
              <p className="text-[0.8125rem] font-medium">{name}</p>
              <p className="text-[0.6875rem] leading-snug text-white/55">{note}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col bg-surface">
        <div className="flex justify-end px-4 pt-4 sm:px-6">
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center px-4 py-8 sm:px-8">
          <div className="w-full max-w-md">
            <h1 className="text-xl font-semibold text-ink">{title}</h1>
            <p className="mt-1 text-[0.8125rem] text-muted">{subtitle}</p>
            <div className="mt-6">{children}</div>
          </div>
        </div>
        <p className="px-4 pb-6 text-center text-xs leading-relaxed text-muted sm:px-8">
          {DISCLAIMER}
        </p>
      </section>
    </div>
  )
}

/** The trace across the dark panel. Decorative: it plots nothing and is hidden from readers. */
function Waveform() {
  return (
    <svg
      viewBox="0 0 600 120"
      preserveAspectRatio="none"
      aria-hidden
      className="pointer-events-none absolute inset-x-0 bottom-32 h-28 w-full opacity-60 lg:bottom-36"
    >
      <path
        d="M0 76 L40 76 L52 44 L64 96 L76 60 L88 76 L132 76 L146 30 L158 104 L170 56 L182 76 L240 76 L254 50 L266 90 L278 62 L290 76 L344 76 L358 38 L370 98 L382 58 L394 76 L452 76 L466 46 L478 94 L490 60 L502 76 L600 76"
        fill="none"
        stroke="#14B8C4"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
