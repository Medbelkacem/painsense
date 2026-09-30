import { cn } from '@/utils/cn'

type Tone = 'colour' | 'mono' | 'reversed'

/**
 * The PainSense mark: a head, a pair of shoulders, and a waveform across the chest.
 *
 * Three tones, as the brand sheet sets them out. The coloured one puts Neural Violet in
 * the head and Signal Teal on the waveform; the monochrome pair is a single ink or white
 * so the mark survives a fax, a stamp or a dark sidebar.
 */
export function Mark({ tone = 'colour', className }: { tone?: Tone; className?: string }) {
  const body =
    tone === 'reversed' ? '#ffffff' : tone === 'mono' ? 'var(--brand-ink)' : 'var(--mark-body)'
  const dot = tone === 'colour' ? 'var(--brand-violet)' : body
  const wave = tone === 'colour' ? 'var(--brand-teal)' : body

  return (
    <svg
      viewBox="0 0 48 48"
      className={cn('shrink-0', className)}
      fill="none"
      role="img"
      aria-label="PainSense"
    >
      <circle cx="24" cy="12.4" r="6.1" stroke={body} strokeWidth="3.6" />
      <circle cx="24" cy="12.4" r="2.5" fill={dot} />
      <path
        d="M9.4 42.6V33.4a14.6 14.6 0 0 1 29.2 0v9.2"
        stroke={body}
        strokeWidth="3.6"
        strokeLinecap="round"
      />
      <path
        d="M12.6 34.2h4.2l2.4-6.4 3.6 12.2 3.1-9.6 2 3.8h5.5"
        stroke={wave}
        strokeWidth="3.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** "PainSense" in Clinical Blue, "AI" a weight lighter in Signal Teal after a wider gap. */
export function Wordmark({
  tone = 'colour',
  className,
}: {
  tone?: Tone
  className?: string
}) {
  const name =
    tone === 'reversed' ? 'text-white' : tone === 'mono' ? 'text-brand-ink' : 'text-mark-word'
  const ai = tone === 'colour' ? 'text-teal' : name

  return (
    <span className={cn('wordmark whitespace-nowrap', name, className)}>
      PainSense<span className={cn('ml-[0.22em] font-medium', ai)}>AI</span>
    </span>
  )
}

export function Lockup({
  tone = 'colour',
  tagline = false,
  className,
  markClassName = 'size-8',
  wordClassName = 'text-xl',
}: {
  tone?: Tone
  tagline?: boolean
  className?: string
  markClassName?: string
  wordClassName?: string
}) {
  return (
    <span className={cn('inline-flex flex-col gap-0.5', className)}>
      <span className="inline-flex items-center gap-2.5">
        <Mark tone={tone} className={markClassName} />
        <Wordmark tone={tone} className={wordClassName} />
      </span>
      {tagline && (
        <span
          className={cn(
            'text-[0.6875rem]',
            tone === 'reversed' ? 'text-white/65' : 'text-muted',
          )}
        >
          Intelligent pain assessment &middot; Clinical decision support
        </span>
      )}
    </span>
  )
}
