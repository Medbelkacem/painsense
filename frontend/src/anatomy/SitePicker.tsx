import React, { useMemo, useRef, useState } from 'react';
import { ChevronRight, Info, Plus, Search, Trash2 } from 'lucide-react';

import { useQuery } from '../api/hooks';
import type {
  AnatomicalSiteIn,
  AnatomicalStructure,
  AnatomyOntology,
  Course,
  Onset,
  PainQuality,
  PainSiteRole,
  Pattern,
  Side,
  StructureType,
} from '../api/types';
import { BodyViewer, type BodyViewerHandle } from './BodyViewer';
import { TISSUE } from './palette';
import type { PickedSite } from './scene';
import { Button } from '../ui/Button';
import { Card, CardHead } from '../ui/Card';
import { Choice, SearchField } from '../ui/Field';
import { Select } from '../ui/Dropdown';
import { Pill } from '../ui/Pill';
import { NrsScale } from '../ui/NrsScale';
import { cx } from '../lib/cx';

const SIDE_LABEL: Record<Side, string> = {
  LEFT: 'Left',
  RIGHT: 'Right',
  BILATERAL: 'Both',
  MIDLINE: 'Midline',
  NOT_APPLICABLE: 'Not applicable',
};

const ROLES: { value: PainSiteRole; label: string; hint: string }[] = [
  { value: 'PRIMARY', label: 'Primary', hint: 'Where it hurts most' },
  { value: 'SECONDARY', label: 'Secondary', hint: 'Also painful' },
  { value: 'RADIATING', label: 'Radiating', hint: 'Travels here from elsewhere' },
  { value: 'REFERRED', label: 'Referred', hint: 'Felt here, arising elsewhere' },
];

const ONSETS: { value: Onset; label: string }[] = [
  { value: 'SUDDEN', label: 'Sudden' },
  { value: 'GRADUAL', label: 'Gradual' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const PATTERNS: { value: Pattern; label: string }[] = [
  { value: 'CONSTANT', label: 'Constant' },
  { value: 'INTERMITTENT', label: 'Comes and goes' },
  { value: 'EPISODIC', label: 'In episodes' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const COURSES: { value: Course; label: string }[] = [
  { value: 'IMPROVING', label: 'Improving' },
  { value: 'STABLE', label: 'Unchanged' },
  { value: 'WORSENING', label: 'Worsening' },
  { value: 'PROGRESSIVE', label: 'Progressive' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const defaultSide = (structure: AnatomicalStructure): Side => structure.sides[0] ?? 'MIDLINE';

interface SitePickerProps {
  sites: readonly AnatomicalSiteIn[];
  onChange: (sites: AnatomicalSiteIn[]) => void;
  /** The quality vocabulary, so each site can carry what the pain feels like there. */
  qualities: readonly PainQuality[];
}

/**
 * Picking where the pain is, on the figure and in the ontology.
 *
 * A site is more than a location: the side, whether it is the worst of them, what it
 * feels like there, how intense it is and how it has behaved are all recorded per site,
 * because a patient with a shoulder and a knee rarely has the same pain in both.
 */
export const SitePicker: React.FC<SitePickerProps> = ({ sites, onChange, qualities }) => {
  const ontology = useQuery<AnatomyOntology>('/api/anatomy');
  const [picked, setPicked] = useState<PickedSite | null>(null);
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<StructureType | 'ALL'>('ALL');
  const [open, setOpen] = useState<string | null>(null);
  const viewer = useRef<BodyViewerHandle | null>(null);

  const structures = ontology.data?.structures ?? [];
  const types = ontology.data?.structure_types ?? [];

  const byCode = useMemo(
    () => new Map(structures.map((structure) => [structure.code, structure])),
    [structures],
  );
  const typeLabel = useMemo(
    () => new Map(types.map((type) => [type.code, type.label])),
    [types],
  );

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return structures
      .filter((structure) => {
        if (!structure.pain_selectable) return false;
        if (typeFilter !== 'ALL' && structure.structure_type !== typeFilter) return false;
        if (!needle) return true;
        return (
          structure.label.toLowerCase().includes(needle) ||
          structure.latin.toLowerCase().includes(needle) ||
          structure.synonyms.some((synonym) => synonym.toLowerCase().includes(needle))
        );
      })
      .slice(0, 160);
  }, [structures, query, typeFilter]);

  const key = (site: AnatomicalSiteIn) => `${site.structure_code}:${site.side}`;
  const labelOf = (code: string) => byCode.get(code)?.label ?? code;

  const show = (structure: AnatomicalStructure, side = defaultSide(structure)) => {
    setPicked({ code: structure.code, side });
    viewer.current?.focus(structure.code, side, structure.structure_type);
  };

  const add = (structure: AnatomicalStructure, side: Side) => {
    const candidate = `${structure.code}:${side}`;
    if (sites.some((site) => key(site) === candidate)) {
      setOpen(candidate);
      return;
    }
    const first = sites.length === 0;
    const next: AnatomicalSiteIn = {
      structure_code: structure.code,
      side,
      role: first ? 'PRIMARY' : 'SECONDARY',
      sequence: sites.length,
      quality_codes: [],
      onset: 'UNKNOWN',
      pattern: 'UNKNOWN',
      course: 'UNKNOWN',
      intensity: null,
      is_primary: first,
    };
    onChange([...sites, next]);
    setOpen(candidate);
  };

  const patch = (target: string, changes: Partial<AnatomicalSiteIn>) =>
    onChange(sites.map((site) => (key(site) === target ? { ...site, ...changes } : site)));

  /** Promoting a site demotes whichever one held the role — there is one worst site. */
  const promote = (target: string) =>
    onChange(
      sites.map((site) =>
        key(site) === target
          ? { ...site, role: 'PRIMARY', is_primary: true }
          : site.is_primary
            ? { ...site, role: 'SECONDARY', is_primary: false }
            : site,
      ),
    );

  const drop = (target: string) =>
    onChange(
      sites
        .filter((site) => key(site) !== target)
        .map((site, index) => ({ ...site, sequence: index })),
    );

  const toggleQuality = (target: string, code: string) => {
    const site = sites.find((entry) => key(entry) === target);
    if (!site) return;
    patch(target, {
      quality_codes: site.quality_codes.includes(code)
        ? site.quality_codes.filter((entry) => entry !== code)
        : [...site.quality_codes, code],
    });
  };

  const current = picked ? byCode.get(picked.code) : undefined;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="p-4">
          {ontology.loading ? (
            <div className="grid h-[520px] place-items-center text-xs text-faint">
              Building the figure…
            </div>
          ) : ontology.error ? (
            <div className="grid h-[520px] place-items-center px-6 text-center text-xs text-danger">
              The anatomy could not be loaded: {ontology.error}
            </div>
          ) : (
            <BodyViewer
              structures={structures}
              types={types}
              selected={picked}
              onPick={setPicked}
              handleRef={viewer}
            />
          )}
        </Card>

        <div className="space-y-4">
          <Card className="p-4">
            {current ? (
              <div className="space-y-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: TISSUE[current.structure_type] }}
                    />
                    <span className="eyebrow">
                      {typeLabel.get(current.structure_type) ?? current.structure_type}
                    </span>
                  </div>
                  <h3 className="mt-1 text-[15px] font-semibold text-ink">{current.label}</h3>
                  {current.latin && <p className="text-[11px] text-mute italic">{current.latin}</p>}
                </div>
                {current.description && (
                  <p className="text-[11.5px] leading-relaxed text-soft">{current.description}</p>
                )}
                {current.pain_selectable ? (
                  <div className="flex flex-wrap gap-1.5 border-t border-hairline pt-3">
                    {(current.sides.length > 0 ? current.sides : (['MIDLINE'] as Side[]))
                      .filter((side) => side !== 'NOT_APPLICABLE')
                      .map((side) => (
                        <Button
                          key={side}
                          size="sm"
                          variant={picked?.side === side ? 'primary' : 'secondary'}
                          icon={<Plus className="h-3.5 w-3.5" />}
                          onClick={() => add(current, side)}
                        >
                          {SIDE_LABEL[side]}
                        </Button>
                      ))}
                  </div>
                ) : (
                  <p className="border-t border-hairline pt-3 text-[11px] text-faint">
                    This structure is reference only and cannot be recorded as a site of pain.
                  </p>
                )}
              </div>
            ) : (
              <div className="py-5 text-center">
                <p className="text-[13px] font-medium text-ink">Nothing picked yet</p>
                <p className="mt-1 text-[11.5px] text-mute">
                  Click the figure or search below, then add the side that hurts. Switch to
                  "Inside" to reach what is under the skin.
                </p>
              </div>
            )}
          </Card>

          <Card className="space-y-3 p-4">
            <SearchField
              icon={<Search className="h-4 w-4" />}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find a structure — knee, sciatic, L5…"
            />
            <div className="flex flex-wrap gap-1">
              <Chip active={typeFilter === 'ALL'} onClick={() => setTypeFilter('ALL')}>
                All
              </Chip>
              {types.map((type) => (
                <Chip
                  key={type.code}
                  active={typeFilter === type.code}
                  colour={TISSUE[type.code]}
                  onClick={() => setTypeFilter(type.code)}
                >
                  {type.label}
                </Chip>
              ))}
            </div>
            <ul className="max-h-[300px] divide-y divide-hairline overflow-y-auto rounded-[10px] border border-hairline">
              {matches.length === 0 && (
                <li className="px-3 py-6 text-center text-xs text-faint">
                  Nothing matches “{query}”.
                </li>
              )}
              {matches.map((structure) => (
                <li key={structure.code}>
                  <button
                    type="button"
                    onClick={() => show(structure)}
                    className={cx(
                      'flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors',
                      structure.code === picked?.code ? 'bg-accent-wash' : 'hover:bg-sunken',
                    )}
                  >
                    <span
                      aria-hidden
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: TISSUE[structure.structure_type] }}
                    />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                      {structure.label}
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-faint" />
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Card className="p-4">
        <CardHead
          title="Sites of pain"
          sub={
            sites.length === 0
              ? 'Add at least one site — the estimate needs to know where the pain is.'
              : `${sites.length} recorded · the primary site is the one that hurts most`
          }
        />
        {sites.length === 0 ? (
          <p className="py-8 text-center text-[13px] text-mute">No site recorded yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {sites.map((site) => {
              const id = key(site);
              const expanded = open === id;
              return (
                <li key={id} className="rounded-[10px] border border-hairline bg-surface">
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
                    <button
                      type="button"
                      onClick={() => setOpen(expanded ? null : id)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      <ChevronRight
                        className={cx(
                          'h-3.5 w-3.5 shrink-0 text-faint transition-transform',
                          expanded && 'rotate-90',
                        )}
                      />
                      <span className="truncate text-[13px] font-medium text-ink">
                        {labelOf(site.structure_code)}
                      </span>
                      {site.side !== 'NOT_APPLICABLE' && (
                        <span className="shrink-0 text-[11px] text-mute">
                          {SIDE_LABEL[site.side].toLowerCase()}
                        </span>
                      )}
                    </button>
                    {site.is_primary ? (
                      <Pill tone="accent" size="xs">
                        Primary
                      </Pill>
                    ) : (
                      <button
                        type="button"
                        onClick={() => promote(id)}
                        className="text-[11px] text-mute hover:text-ink hover:underline"
                      >
                        Make primary
                      </button>
                    )}
                    {site.intensity !== null && site.intensity !== undefined && (
                      <Pill size="xs" tone="neutral">
                        {site.intensity}/10
                      </Pill>
                    )}
                    <button
                      type="button"
                      onClick={() => drop(id)}
                      aria-label={`Remove ${labelOf(site.structure_code)}`}
                      className="rounded-md p-1 text-faint transition-colors hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {expanded && (
                    <div className="space-y-4 border-t border-hairline px-3 py-3.5">
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <Field label="Role">
                          <Select
                            label="Role"
                            className="w-full [&>button]:w-full"
                            options={ROLES.map((role) => ({
                              value: role.value,
                              label: role.label,
                              hint: role.hint,
                            }))}
                            value={site.role}
                            onChange={(value) =>
                              value === 'PRIMARY'
                                ? promote(id)
                                : patch(id, { role: value as PainSiteRole, is_primary: false })
                            }
                          />
                        </Field>
                        <Field label="Onset here">
                          <Select
                            label="Onset"
                            className="w-full [&>button]:w-full"
                            options={ONSETS}
                            value={site.onset}
                            onChange={(value) => patch(id, { onset: value as Onset })}
                          />
                        </Field>
                        <Field label="Pattern">
                          <Select
                            label="Pattern"
                            className="w-full [&>button]:w-full"
                            options={PATTERNS}
                            value={site.pattern}
                            onChange={(value) => patch(id, { pattern: value as Pattern })}
                          />
                        </Field>
                        <Field label="Course">
                          <Select
                            label="Course"
                            className="w-full [&>button]:w-full"
                            options={COURSES}
                            value={site.course}
                            onChange={(value) => patch(id, { course: value as Course })}
                          />
                        </Field>
                      </div>

                      {site.role === 'RADIATING' && (
                        <Field label="Radiating from">
                          <Select
                            label="Pick the site it travels from"
                            className="w-full [&>button]:w-full"
                            searchable
                            options={sites
                              .filter((entry) => key(entry) !== id)
                              .map((entry) => ({
                                value: entry.structure_code,
                                label: labelOf(entry.structure_code),
                                hint: SIDE_LABEL[entry.side],
                              }))}
                            value={site.radiation_from_code ?? null}
                            onChange={(value) => {
                              const from = sites.find((entry) => entry.structure_code === value);
                              patch(id, {
                                radiation_from_code: value,
                                radiation_from_side: from?.side ?? null,
                              });
                            }}
                          />
                        </Field>
                      )}

                      <div>
                        <span className="mb-1.5 block text-xs font-medium text-soft">
                          Intensity at this site
                        </span>
                        <NrsScale
                          value={site.intensity ?? null}
                          onChange={(value) => patch(id, { intensity: value })}
                        />
                      </div>

                      {qualities.length > 0 && (
                        <div>
                          <span className="mb-1.5 block text-xs font-medium text-soft">
                            What it feels like here
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {qualities.map((quality) => (
                              <Choice
                                key={quality.code}
                                kind="check"
                                checked={site.quality_codes.includes(quality.code)}
                                onClick={() => toggleQuality(id, quality.code)}
                              >
                                {quality.label}
                              </Choice>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {ontology.data && (
          <p className="mt-3 flex gap-2 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {ontology.data.notice}
          </p>
        )}
      </Card>
    </div>
  );
};

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    {children}
  </div>
);

function Chip({
  active,
  colour,
  onClick,
  children,
}: {
  active: boolean;
  colour?: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
        active
          ? 'border-accent-edge bg-accent-wash text-accent-ink'
          : 'border-hairline text-mute hover:text-soft',
      )}
    >
      {colour && (
        <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: colour }} />
      )}
      {children}
    </button>
  );
}
