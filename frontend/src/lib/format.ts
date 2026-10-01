const DAY = 86_400_000;

/** "Today, 14:32" / "Yesterday, 09:14" / "24 Sep, 16:50" — the table's time column. */
export function whenShort(at: Date): string {
  const reference = new Date();
  const clock = at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const days = Math.floor((startOfDay(reference) - startOfDay(at)) / DAY);
  if (days === 0) return `Today, ${clock}`;
  if (days === 1) return `Yesterday, ${clock}`;
  return `${at.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}, ${clock}`;
}

export function whenRelative(at: Date): string {
  const minutes = Math.round((Date.now() - at.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export function dateLong(at: Date): string {
  return at.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function startOfDay(at: Date): number {
  return new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
}

export function initials(name: string | undefined | null): string {
  if (!name) return '—';
  return name
    .replace(/^Dr\.?\s*/i, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

export function percent(part: number, total: number): string {
  if (total === 0) return '0%';
  return `${Math.round((part / total) * 100)}%`;
}
