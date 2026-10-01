/**
 * Status chips for the data-acquisition screens.
 *
 * The backend reports several small enumerations — how a source may be accessed, what a
 * licence allows, whether a file passed validation — and each one needs the same
 * treatment: a short human word plus a colour that means the same thing everywhere.
 * `tone` is a raw class string so a caller can pass a map it already keeps, which is how
 * the signal pages colour their own stage machines.
 */
import React from 'react';
import type {
  Availability,
  Granularity,
  LicenceVerdict,
  QualityStatus,
  SourceAccess,
  SyncOutcome,
} from '../../api/types';

export const Pill: React.FC<{
  tone?: string;
  title?: string;
  children: React.ReactNode;
}> = ({ tone = 'bg-sunken text-mute border-hairline', title, children }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium whitespace-nowrap ${tone}`}
  >
    {children}
  </span>
);

const OK = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
const INFO = 'bg-sky-500/10 text-sky-300 border-sky-500/30';
const WARN = 'bg-amber-500/10 text-amber-300 border-amber-500/30';
const BAD = 'bg-red-500/10 text-red-300 border-red-500/30';
const MUTED = 'bg-sunken text-mute border-hairline';

const ACCESS: Record<SourceAccess, { label: string; tone: string }> = {
  OPEN: { label: 'open', tone: OK },
  REGISTRATION_REQUIRED: { label: 'registration', tone: INFO },
  CREDENTIALED: { label: 'credentialed', tone: WARN },
  AGREEMENT_REQUIRED: { label: 'agreement', tone: WARN },
  DOCUMENT_ONLY: { label: 'document only', tone: MUTED },
  UNKNOWN: { label: 'unknown', tone: MUTED },
};

const AVAILABILITY: Record<Availability, { label: string; tone: string }> = {
  AVAILABLE: { label: 'held', tone: OK },
  METADATA_ONLY: { label: 'metadata only', tone: INFO },
  NOT_ATTEMPTED: { label: 'not fetched', tone: MUTED },
  FAILED: { label: 'fetch failed', tone: BAD },
};

const LICENCE: Record<LicenceVerdict, { label: string; tone: string }> = {
  PERMISSIVE: { label: 'permissive', tone: OK },
  RESEARCH_ONLY: { label: 'research only', tone: INFO },
  REVIEW_REQUIRED: { label: 'review required', tone: WARN },
  RESTRICTED: { label: 'restricted', tone: BAD },
  UNKNOWN: { label: 'licence unknown', tone: MUTED },
};

const GRANULARITY: Record<Granularity, { label: string; tone: string }> = {
  SUBJECT_LEVEL: { label: 'subject level', tone: OK },
  AGGREGATE: { label: 'aggregate', tone: INFO },
  UNKNOWN: { label: 'granularity unknown', tone: MUTED },
};

const QUALITY: Record<QualityStatus, { label: string; tone: string }> = {
  PASSED: { label: 'passed', tone: OK },
  PASSED_WITH_WARNINGS: { label: 'warnings', tone: WARN },
  FAILED: { label: 'failed', tone: BAD },
  NOT_ASSESSED: { label: 'not assessed', tone: MUTED },
};

export const AccessPill: React.FC<{ value: SourceAccess }> = ({ value }) => (
  <Pill tone={ACCESS[value].tone}>{ACCESS[value].label}</Pill>
);

export const AvailabilityPill: React.FC<{ value: Availability }> = ({ value }) => (
  <Pill tone={AVAILABILITY[value].tone}>{AVAILABILITY[value].label}</Pill>
);

export const LicencePill: React.FC<{ value: LicenceVerdict }> = ({ value }) => (
  <Pill tone={LICENCE[value].tone}>{LICENCE[value].label}</Pill>
);

export const GranularityPill: React.FC<{ value: Granularity }> = ({ value }) => (
  <Pill tone={GRANULARITY[value].tone}>{GRANULARITY[value].label}</Pill>
);

export const QualityPill: React.FC<{ value: QualityStatus }> = ({ value }) => (
  <Pill tone={QUALITY[value].tone}>{QUALITY[value].label}</Pill>
);

/** A run's per-stage result, small enough that a dot carries it. */
export const OutcomeDot: React.FC<{ value: SyncOutcome }> = ({ value }) => (
  <span
    title={value.toLowerCase()}
    className={`inline-block h-2 w-2 shrink-0 rounded-full ${
      value === 'OK' ? 'bg-emerald-500' : value === 'SKIPPED' ? 'bg-slate-600' : 'bg-red-500'
    }`}
  />
);

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['kB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** Absolute date for anything older than a day — "2 d ago" is not a useful audit trail. */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return 'never';
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return '—';
  const minutes = Math.round((Date.now() - at.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return at.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
