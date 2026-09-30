import type { BandCode } from '@/api/types'

/**
 * Colours for the 3D model, read from the same CSS tokens as the rest of the interface so
 * the pain bands mean the same thing on the model, on the scale and in the report.
 *
 * The fallbacks are the token values. They are used where there is no document to read
 * from, which is the case under the test runner.
 */
const FALLBACK: Record<string, string> = {
  '--color-accent': '#0e7490',
  '--color-accent-strong': '#115e72',
  '--color-band-none': '#0f766e',
  '--color-band-mild': '#15803d',
  '--color-band-moderate': '#b45309',
  '--color-band-severe': '#c2410c',
  '--color-band-extreme': '#b91c1c',
}

export function token(name: string): string {
  if (typeof document === 'undefined') return FALLBACK[name] ?? '#888888'
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || FALLBACK[name] || '#888888'
}

/** Tissue colours. Not tokens: they belong to the anatomy, not to the product's palette. */
export const TISSUE: Record<string, string> = {
  REGION: '#ccd7e0',
  MUSCLE: '#b4564c',
  TENDON: '#d9cfb4',
  BONE: '#e8e4d8',
  JOINT: '#7fa6bd',
  ORGAN: '#8c5a7a',
  NERVE: '#d8a83a',
  VESSEL: '#9b2f2f',
}

/** The band a 0-10 score falls in, matching the server's boundaries. */
export function bandOf(score: number): BandCode {
  if (score < 1) return 'NONE'
  if (score < 4) return 'MILD'
  if (score < 7) return 'MODERATE'
  if (score < 10) return 'SEVERE'
  return 'EXTREME'
}

const BAND_TOKEN: Record<BandCode, string> = {
  NONE: '--color-band-none',
  MILD: '--color-band-mild',
  MODERATE: '--color-band-moderate',
  SEVERE: '--color-band-severe',
  EXTREME: '--color-band-extreme',
}

/**
 * The colour a selected site is drawn in: its pain band where one was recorded, and the
 * interface accent where the intensity has not been given yet.
 */
export function siteColour(intensity?: number | null): string {
  if (intensity === null || intensity === undefined) return token('--color-accent')
  return token(BAND_TOKEN[bandOf(intensity)])
}
