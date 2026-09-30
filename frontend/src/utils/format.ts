const DATE = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
const DATE_TIME = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export const formatDate = (value?: string | null) => (value ? DATE.format(new Date(value)) : '—')
export const formatDateTime = (value?: string | null) =>
  value ? DATE_TIME.format(new Date(value)) : '—'

export function formatRelative(value?: string | null) {
  if (!value) return '—'
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return days < 31 ? `${days} d ago` : formatDate(value)
}

export const formatScore = (value?: number | null, digits = 1) =>
  value === null || value === undefined ? '—' : value.toFixed(digits)

export const formatSigned = (value?: number | null, digits = 1) =>
  value === null || value === undefined ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)}`

export const formatPercent = (value?: number | null) =>
  value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`

/** Turns SCREAMING_SNAKE codes into something readable when no label was supplied. */
export const humanise = (code?: string | null) =>
  !code ? '—' : code.charAt(0) + code.slice(1).toLowerCase().replaceAll('_', ' ')
