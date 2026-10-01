import React, { useMemo, useState } from 'react';
import { Download, FileText, Printer } from 'lucide-react';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill } from '../ui/Pill';
import { Select } from '../ui/Dropdown';
import { Segmented } from '../ui/Segmented';
import { Toggle } from '../ui/Field';
import { Logo } from '../ui/Logo';
import { BAND_VAR, bandOf, BAND_LABEL, Sparkline } from '../ui/charts';
import { historyFor, now, patients } from '../demo/cohort';
import { whenShort } from '../lib/format';
import { cx } from '../lib/cx';

const SECTIONS = [
  { key: 'summary', label: 'Patient summary', always: true },
  { key: 'assessments', label: 'Pain assessments' },
  { key: 'vitals', label: 'Vitals' },
  { key: 'estimate', label: 'AI estimate and range' },
  { key: 'flags', label: 'Red flags' },
  { key: 'medication', label: 'Medication' },
  { key: 'trend', label: 'Pain trend' },
  { key: 'audit', label: 'Audit trail' },
] as const;

type SectionKey = (typeof SECTIONS)[number]['key'];

export const Reports: React.FC = () => {
  const [code, setCode] = useState(patients[0].code);
  const [span, setSpan] = useState<'30d' | '90d' | '1y'>('30d');
  const [zoom, setZoom] = useState<'fit' | 'full'>('fit');
  const [enabled, setEnabled] = useState<Record<SectionKey, boolean>>({
    summary: true, assessments: true, vitals: true, estimate: true,
    flags: true, medication: false, trend: true, audit: false,
  });

  const patient = patients.find((entry) => entry.code === code) ?? patients[0];
  const history = useMemo(() => historyFor(patient), [patient]);
  const band = bandOf(patient.nrs);

  const recent = patients.slice(0, 4).map((entry, index) => ({
    id: `RP-2026-${String(1180 + index).padStart(4, '0')}`,
    patient: entry.code,
    at: new Date(now().getTime() - (index + 1) * 5_400_000),
  }));

  return (
    <>
      <PageHead
        title="Reports"
        sub="Generate a clinical summary from the recorded assessments. Every figure on the page is traceable."
        action={
          <>
            <Button icon={<Printer className="h-4 w-4" />}>Print</Button>
            <Button variant="primary" icon={<Download className="h-4 w-4" />}>
              Download PDF
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Card className="p-5">
            <CardHead title="Generate clinical report" sub="Pick what goes in" />
            <div className="mt-4 space-y-3">
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-soft">Patient</span>
                <Select
                  label="Select"
                  className="w-full [&>button]:w-full"
                  searchable
                  clearable={false}
                  options={patients.slice(0, 24).map((entry) => ({
                    value: entry.code,
                    label: entry.code,
                    hint: `NRS ${entry.nrs}`,
                  }))}
                  value={code}
                  onChange={(value) => setCode(value ?? patients[0].code)}
                />
              </div>
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-soft">Period</span>
                <Segmented
                  className="w-full"
                  options={[
                    { value: '30d', label: '30 days' },
                    { value: '90d', label: '3 months' },
                    { value: '1y', label: '1 year' },
                  ]}
                  value={span}
                  onChange={setSpan}
                />
              </div>
            </div>

            <p className="eyebrow mt-5 mb-2">Sections</p>
            <ul className="divide-y divide-hairline">
              {SECTIONS.map((section) => (
                <li key={section.key} className="flex items-center justify-between gap-3 py-2">
                  <span className="text-[13px] text-soft">
                    {section.label}
                    {'always' in section && section.always && (
                      <span className="ml-1.5 text-[10px] text-faint">required</span>
                    )}
                  </span>
                  <Toggle
                    label={section.label}
                    hideLabel
                    checked={enabled[section.key]}
                    onChange={(value) =>
                      setEnabled((state) => ({
                        ...state,
                        [section.key]: 'always' in section && section.always ? true : value,
                      }))
                    }
                  />
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-5">
            <CardHead title="Recent reports" sub="Kept for 7 years" />
            <ul className="mt-3 divide-y divide-hairline">
              {recent.map((report) => (
                <li key={report.id} className="flex items-center gap-3 py-2.5">
                  <FileText className="h-4 w-4 shrink-0 text-faint" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12.5px] font-medium text-ink">{report.id}</p>
                    <p className="truncate text-[11px] text-mute">
                      {report.patient} · {whenShort(report.at)}
                    </p>
                  </div>
                  <Button size="sm" variant="ghost">
                    Open
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <Card className="p-5">
          <CardHead
            title="Preview"
            sub="What the exported PDF will contain"
            action={
              <Segmented
                options={[
                  { value: 'fit', label: 'Fit' },
                  { value: 'full', label: '100%' },
                ]}
                value={zoom}
                onChange={setZoom}
              />
            }
          />

          {/* An A4-proportioned sheet rather than a styled card: what you see is the page
              that comes out of the printer. */}
          <div className="mt-4 flex justify-center overflow-x-auto rounded-xl bg-sunken p-5">
            <article
              className={cx(
                'w-full shrink-0 rounded-sm bg-white p-8 text-[#0b1b33] shadow-pop',
                zoom === 'fit' ? 'max-w-[640px]' : 'max-w-none',
              )}
              style={zoom === 'full' ? { width: 794 } : undefined}
            >
              <header className="flex items-start justify-between border-b border-[#e3e8f2] pb-4">
                <Logo size="sm" />
                <div className="text-right text-[10px] text-[#74849f]">
                  <p className="font-semibold text-[#0b1b33]">Clinical assessment report</p>
                  <p>Generated {whenShort(now())}</p>
                  <p>Reference RP-2026-1184</p>
                </div>
              </header>

              <h2 className="mt-5 text-[15px] font-semibold">Patient summary</h2>
              <dl className="mt-2 grid grid-cols-2 gap-x-8 gap-y-1 text-[11px]">
                {[
                  ['Patient', patient.code],
                  ['Age / sex', `${patient.age} · ${patient.sex === 'F' ? 'Female' : 'Male'}`],
                  ['Unit', patient.unit],
                  ['Pain type', patient.painType],
                  ['Responsible clinician', patient.clinician],
                  ['Last assessment', whenShort(patient.lastAt)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between border-b border-[#eef1f6] py-1">
                    <dt className="text-[#74849f]">{label}</dt>
                    <dd className="font-medium">{value}</dd>
                  </div>
                ))}
              </dl>

              {enabled.estimate && (
                <>
                  <h2 className="mt-5 text-[15px] font-semibold">Pain and model estimate</h2>
                  <div className="mt-2 flex gap-3">
                    <div className="flex-1 rounded-md border border-[#e3e8f2] p-3">
                      <p className="text-[10px] text-[#74849f]">Patient-reported NRS</p>
                      <p className="text-[22px] leading-tight font-semibold" style={{ color: BAND_VAR[band] }}>
                        {patient.nrs} <span className="text-[11px] text-[#74849f]">/ 10</span>
                      </p>
                      <p className="text-[10px] text-[#74849f]">{BAND_LABEL[band]}</p>
                    </div>
                    <div className="flex-1 rounded-md border border-[#e3e8f2] p-3">
                      <p className="text-[10px] text-[#74849f]">AI estimate</p>
                      <p className="text-[22px] leading-tight font-semibold text-[#7c5cff]">
                        {patient.estimate.toFixed(1)}
                      </p>
                      <p className="text-[10px] text-[#74849f]">
                        Range {(patient.estimate - patient.spread).toFixed(1)} –{' '}
                        {(patient.estimate + patient.spread).toFixed(1)}
                      </p>
                    </div>
                    <div className="flex-1 rounded-md border border-[#e3e8f2] p-3">
                      <p className="text-[10px] text-[#74849f]">Clinical priority</p>
                      <p className="text-[22px] leading-tight font-semibold">{patient.priority}</p>
                      <p className="text-[10px] text-[#74849f]">Rule-based</p>
                    </div>
                  </div>
                </>
              )}

              {enabled.trend && (
                <>
                  <h2 className="mt-5 text-[15px] font-semibold">Pain trend</h2>
                  <div className="mt-2 rounded-md border border-[#e3e8f2] p-3">
                    <Sparkline
                      values={history.map((point) => point.reported)}
                      tone="#0b3c7d"
                      className="h-16"
                    />
                    <div className="mt-1 flex justify-between text-[9px] text-[#74849f]">
                      <span>{history[0].label}</span>
                      <span>{history.at(-1)!.label}</span>
                    </div>
                  </div>
                </>
              )}

              {enabled.vitals && (
                <>
                  <h2 className="mt-5 text-[15px] font-semibold">Vitals</h2>
                  <table className="mt-2 w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-[#e3e8f2] text-left text-[#74849f]">
                        <th className="py-1 font-medium">HR</th>
                        <th className="py-1 font-medium">RR</th>
                        <th className="py-1 font-medium">BP</th>
                        <th className="py-1 font-medium">SpO₂</th>
                        <th className="py-1 font-medium">Temp</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="py-1.5">{patient.vitals.hr} bpm</td>
                        <td className="py-1.5">{patient.vitals.rr} /min</td>
                        <td className="py-1.5">
                          {patient.vitals.sys}/{patient.vitals.dia} mmHg
                        </td>
                        <td className="py-1.5">{patient.vitals.spo2} %</td>
                        <td className="py-1.5">{patient.vitals.temp} °C</td>
                      </tr>
                    </tbody>
                  </table>
                </>
              )}

              {enabled.flags && patient.nrs >= 7 && (
                <div className="mt-5 rounded-md border border-[#f0c99a] bg-[#fdf6ec] p-3">
                  <p className="text-[11px] font-semibold">Clinical review cue</p>
                  <p className="mt-1 text-[10.5px] leading-relaxed text-[#475a78]">
                    Reported intensity of {patient.nrs} falls in the severe band. Same-session review
                    and an analgesia plan are recommended.
                  </p>
                </div>
              )}

              <footer className="mt-6 border-t border-[#e3e8f2] pt-3 text-[9.5px] leading-relaxed text-[#74849f]">
                Clinical decision support only · not a diagnosis. Generated from synthetic
                demonstration data. The patient's self-reported score is the reference value; the
                model estimate is advisory.
              </footer>
            </article>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <Pill tone="violet" dot>
              Synthetic data
            </Pill>
            <p className="text-[11px] text-faint">
              {Object.values(enabled).filter(Boolean).length} of {SECTIONS.length} sections included
            </p>
          </div>
        </Card>
      </div>
    </>
  );
};
