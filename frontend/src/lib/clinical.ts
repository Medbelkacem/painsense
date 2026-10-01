import type { Course, DurationUnit, Onset, Pattern, Sex, SmokingStatus } from '../api/types';

export const SEX_LABEL: Record<Sex, string> = {
  F: 'Female',
  M: 'Male',
  OTHER: 'Other',
  UNDISCLOSED: 'Not disclosed',
};

export const SMOKING_LABEL: Record<SmokingStatus, string> = {
  NEVER: 'Never smoked',
  FORMER: 'Former smoker',
  CURRENT: 'Current smoker',
  UNKNOWN: 'Not known',
};

export const ONSET_OPTIONS: { value: Onset; label: string }[] = [
  { value: 'SUDDEN', label: 'Sudden' },
  { value: 'GRADUAL', label: 'Gradual' },
  { value: 'UNKNOWN', label: 'Not known' },
];

export const PATTERN_OPTIONS: { value: Pattern; label: string }[] = [
  { value: 'CONSTANT', label: 'Constant' },
  { value: 'INTERMITTENT', label: 'Intermittent' },
  { value: 'UNKNOWN', label: 'Not known' },
];

export const COURSE_OPTIONS: { value: Course; label: string }[] = [
  { value: 'IMPROVING', label: 'Improving' },
  { value: 'STABLE', label: 'Stable' },
  { value: 'WORSENING', label: 'Worsening' },
  { value: 'UNKNOWN', label: 'Not known' },
];

export const DURATION_UNITS: { value: DurationUnit; singular: string; plural: string }[] = [
  { value: 'minutes', singular: 'minute', plural: 'minutes' },
  { value: 'hours', singular: 'hour', plural: 'hours' },
  { value: 'days', singular: 'day', plural: 'days' },
  { value: 'months', singular: 'month', plural: 'months' },
  { value: 'years', singular: 'year', plural: 'years' },
];

export function durationLabel(value: number | null, unit: DurationUnit | null): string {
  const entry = DURATION_UNITS.find((item) => item.value === unit);
  if (value === null || !entry) return 'Not recorded';
  return `${value} ${value === 1 ? entry.singular : entry.plural}`;
}

export const NONE_RECORDED = 'None recorded';

/** Enum values as the API spells them, made readable: WORSENING becomes "Worsening". */
export function word(value: string | null | undefined): string {
  if (!value) return NONE_RECORDED;
  const lower = value.toLowerCase().replace(/_/g, ' ');
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

export const DISCLAIMER =
  'AI-assisted prototype. Not a medical diagnosis and not a substitute for clinical judgement.';
