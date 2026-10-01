import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CornerDownLeft, Search, User } from 'lucide-react';
import { allNavItems } from './nav-model';
import { useQuery } from '../api/hooks';
import type { Page, PatientSummary } from '../api/types';
import { cx } from '../lib/cx';

interface Result {
  id: string;
  label: string;
  group: string;
  detail?: string;
  icon: React.ReactNode;
  to: string;
}

/**
 * ⌘K. One box over pages and patients — the fastest route to a patient code, which is how
 * clinicians actually navigate once they know the ward.
 *
 * The patient search is the server's, not a filter over a list held here: a workspace with
 * ten thousand patients cannot be searched in the browser, and the API already matches on
 * code, ward and name.
 */
export const CommandPalette: React.FC<{ open: boolean; onClose: () => void }> = ({
  open,
  onClose,
}) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setIndex(0);
      // Deferred a frame: the input is mounted but not yet laid out on this tick.
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);

  // Debounced, so typing a six-character code is one request rather than six.
  const [needleFor, setNeedleFor] = useState('');
  useEffect(() => {
    const timer = window.setTimeout(() => setNeedleFor(query.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  const people = useQuery<Page<PatientSummary>>(
    open
      ? `/api/patients?limit=6${needleFor ? `&search=${encodeURIComponent(needleFor)}` : ''}`
      : null,
  );

  const results = useMemo<Result[]>(() => {
    const needle = query.trim().toLowerCase();
    const pages: Result[] = allNavItems
      .filter((item) => !needle || item.label.toLowerCase().includes(needle))
      .map((item) => ({
        id: item.path,
        label: item.label,
        group: 'Go to',
        icon: <item.icon className="h-4 w-4" />,
        to: item.path,
      }));

    const found: Result[] = (people.data?.items ?? []).map((patient) => ({
      id: patient.id,
      label: patient.display_name,
      group: 'Patients',
      detail: [
        patient.code,
        patient.age !== null ? `${patient.age}` : null,
        patient.ward,
        patient.latest_self_report !== null ? `reported ${patient.latest_self_report}` : null,
      ]
        .filter(Boolean)
        .join(' · '),
      icon: <User className="h-4 w-4" />,
      to: `/patients/${patient.id}`,
    }));

    return [...pages, ...found].slice(0, 12);
  }, [query, people.data]);

  useEffect(() => {
    if (index > results.length - 1) setIndex(0);
  }, [results.length, index]);

  if (!open) return null;

  function run(result: Result | undefined) {
    if (!result) return;
    navigate(result.to);
    onClose();
  }

  let lastGroup = '';

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center bg-[#0b1b33]/35 px-4 pt-[12vh] backdrop-blur-[2px]"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-label="Search"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-hairline bg-surface shadow-pop animate-[ps-rise_140ms_ease-out]"
      >
        <div className="flex items-center gap-3 border-b border-hairline px-4">
          <Search className="h-4 w-4 shrink-0 text-faint" />
          <input
            ref={input}
            value={query}
            placeholder="Search patients, assessments, reports…"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setIndex((at) => (at + 1) % Math.max(1, results.length));
              } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                setIndex((at) => (at - 1 + results.length) % Math.max(1, results.length));
              } else if (event.key === 'Enter') {
                run(results[index]);
              } else if (event.key === 'Escape') {
                onClose();
              }
            }}
            className="h-14 w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint"
          />
          <kbd className="shrink-0 rounded border border-hairline px-1.5 py-0.5 font-sans text-[10px] text-faint">
            ESC
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-1.5">
          {results.map((result, at) => {
            const heading = result.group !== lastGroup ? result.group : null;
            lastGroup = result.group;
            return (
              <React.Fragment key={result.id}>
                {heading && <p className="eyebrow px-2.5 pt-2.5 pb-1">{heading}</p>}
                <button
                  type="button"
                  onPointerMove={() => setIndex(at)}
                  onClick={() => run(result)}
                  className={cx(
                    'flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13px]',
                    at === index ? 'bg-sunken text-ink' : 'text-soft',
                  )}
                >
                  <span className="text-faint">{result.icon}</span>
                  <span className="flex-1 truncate font-medium">{result.label}</span>
                  {result.detail && (
                    <span className="hidden truncate text-[11px] text-faint sm:block">
                      {result.detail}
                    </span>
                  )}
                  {at === index && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-faint" />}
                </button>
              </React.Fragment>
            );
          })}
          {results.length === 0 && (
            <p className="px-3 py-10 text-center text-[13px] text-faint">
              Nothing matches “{query}”.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
