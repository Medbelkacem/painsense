import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, CircleStop, History, Microscope, Play, Radio, RefreshCw, Usb,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type {
  DeviceScan, LiveView, QualityVerdict, SignalAnalysis, SignalRecording,
  SignalRecordingDetail, SignalReference, SignalWaveform,
} from '../api/types';
import { Trace } from './Trace';
import { Button } from '../ui/Button';
import { Card, CardHead } from '../ui/Card';
import { Select } from '../ui/Dropdown';
import { TextField, Toggle } from '../ui/Field';
import { Pill, type Tone } from '../ui/Pill';
import { cx } from '../lib/cx';

/**
 * EEG and EMG acquisition.
 *
 * The panel has one job beyond driving the workflow: never to imply a pain estimate the
 * platform cannot produce. `/api/signals/reference` reports whether a model exists, and the
 * answer is shown before a recording is started rather than discovered when the report
 * comes back empty.
 *
 * Where samples come from is on screen at every stage. A simulated session is labelled on
 * the control that starts it, on the live panel, on the report and on its history row.
 */

type Stage =
  | 'READY'
  | 'RECORDING'
  | 'PROCESSING'
  | 'SAVED'
  | 'ANALYSED'
  | 'DEVICE_DISCONNECTED'
  | 'UNAVAILABLE';

const STAGE_LABEL: Record<Stage, string> = {
  READY: 'Ready',
  RECORDING: 'Recording',
  PROCESSING: 'Processing',
  SAVED: 'Saved — ready to analyse',
  ANALYSED: 'Analysis completed',
  DEVICE_DISCONNECTED: 'Device not connected',
  UNAVAILABLE: 'Analysis unavailable',
};

const STAGE_TONE: Record<Stage, Tone> = {
  READY: 'neutral',
  RECORDING: 'danger',
  PROCESSING: 'warn',
  SAVED: 'teal',
  ANALYSED: 'ok',
  DEVICE_DISCONNECTED: 'neutral',
  UNAVAILABLE: 'warn',
};

const QUALITY_TONE: Record<QualityVerdict, Tone> = {
  GOOD: 'ok',
  ADEQUATE: 'teal',
  POOR: 'warn',
  UNUSABLE: 'danger',
};

/** Trace colours by modality. These belong to the signal, not to the theme. */
const MODALITY_COLOUR: Record<string, string> = {
  EEG: '#38bdf8',
  EMG: '#a78bfa',
  PPG: '#f87171',
  GSR: '#fbbf24',
  RESPIRATION: '#34d399',
};

type ChannelInfo = { label: string; unit: string; modality: string };

function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (value < 1024) return `${value} B`;
  const units = ['kB', 'MB', 'GB', 'TB'];
  let scaled = value / 1024;
  let unit = 0;
  while (scaled >= 1024 && unit < units.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  return `${scaled < 10 ? scaled.toFixed(1) : Math.round(scaled)} ${units[unit]}`;
}

function when(value: string | null | undefined): string {
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

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
}

interface SignalPanelProps {
  patientId: string | null;
  /** The patient's own score, stored beside the analysis and never fed into it. */
  reportedNrs?: number | null;
  onAnalysis?: (analysis: SignalAnalysis, recording: SignalRecordingDetail) => void;
}

export const SignalPanel: React.FC<SignalPanelProps> = ({
  patientId,
  reportedNrs = null,
  onAnalysis,
}) => {
  const reference = useQuery<SignalReference>('/api/signals/reference');
  const history = useQuery<SignalRecording[]>(
    patientId ? `/api/signals/recordings?patient_id=${patientId}&limit=15` : null,
    30,
  );
  const scan = useQuery<DeviceScan>('/api/signals/devices');

  const [simulate, setSimulate] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [recording, setRecording] = useState<SignalRecordingDetail | null>(null);
  const [stage, setStage] = useState<Stage>('READY');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [trace, setTrace] = useState<SignalWaveform | null>(null);
  const [device, setDevice] = useState<string | null>(null);
  const [emgRate, setEmgRate] = useState('1000');
  const [live, setLive] = useState<LiveView | null>(null);

  const channels = reference.data?.channels ?? [];
  const byCode = useMemo<Record<string, ChannelInfo>>(
    () => Object.fromEntries(channels.map((channel) => [channel.code, channel])),
    [channels],
  );

  // Default to every channel the reference offers, once it lands.
  useEffect(() => {
    if (channels.length > 0 && selected.length === 0) {
      setSelected(channels.map((channel) => channel.code));
    }
  }, [channels, selected.length]);

  // While recording, poll the live view. It carries the elapsed time, the device counters
  // and a decimated window of recent samples, so one request drives the whole live panel.
  const recordingId = recording?.id ?? null;
  useEffect(() => {
    if (stage !== 'RECORDING' || !recordingId) return;
    let cancelled = false;
    const poll = () => {
      request<LiveView>(`/api/signals/recordings/${recordingId}/live?points=700`)
        .then((view) => {
          if (!cancelled) setLive(view);
        })
        .catch(() => {
          /* a dropped poll is not a failed recording; the next one will tell us */
        });
    };
    poll();
    const timer = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [stage, recordingId]);

  const primaryChosen = selected.some((code) => channels.find((c) => c.code === code)?.primary);
  const canStart = Boolean(patientId) && primaryChosen && !busy;

  const start = useCallback(async () => {
    if (!patientId) return;
    setBusy(true);
    setError(null);
    setTrace(null);
    try {
      const chosen = scan.data?.devices.find(
        (candidate) => `${candidate.adapter}:${candidate.identifier}` === device,
      );
      // EEG and surface EMG are recorded on different clocks, so the EMG channels carry
      // their own rate rather than inheriting the session's.
      const rates: Record<string, number> = {};
      const emg = Number(emgRate);
      if (Number.isFinite(emg) && emg > 0) {
        selected
          .filter((code) => byCode[code]?.modality === 'EMG')
          .forEach((code) => {
            rates[code] = emg;
          });
      }
      const body: Record<string, unknown> = {
        patient_id: patientId,
        channels: selected,
        sample_rate_hz: chosen?.sample_rate_hz ?? reference.data?.default_sample_rate_hz ?? 512,
        channel_rates: rates,
        source: simulate ? 'SIMULATION' : 'HARDWARE',
      };
      if (simulate) {
        body.simulate_seconds = 30;
        body.simulate_seed = Math.floor(Math.random() * 100000);
      } else if (chosen) {
        body.adapter = chosen.adapter;
        body.device_identifier = chosen.identifier;
      }
      const started = await request<SignalRecordingDetail>('/api/signals/recordings', {
        method: 'POST',
        body,
      });
      setRecording(started);
      setLive(null);
      setStage('RECORDING');
      history.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not start the recording.');
      setStage(simulate ? 'READY' : 'DEVICE_DISCONNECTED');
    } finally {
      setBusy(false);
    }
  }, [patientId, selected, simulate, reference.data, history, scan.data, device, emgRate, byCode]);

  const stop = useCallback(async () => {
    if (!recording) return;
    setBusy(true);
    setStage('PROCESSING');
    setError(null);
    try {
      const saved = await request<SignalRecordingDetail>(
        `/api/signals/recordings/${recording.id}/stop`,
        { method: 'POST' },
      );
      setRecording(saved);
      setLive(null);
      // Stop saves and validates. Analysis is the operator's next decision, which is why
      // it is a separate control rather than part of this.
      setStage('SAVED');
      history.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The recording could not be saved.');
      setStage('UNAVAILABLE');
    } finally {
      setBusy(false);
    }
  }, [recording, history]);

  const analyse = useCallback(async () => {
    if (!recording) return;
    setBusy(true);
    setError(null);
    try {
      const analysed = await request<SignalRecordingDetail>(
        `/api/signals/recordings/${recording.id}/analyze`,
        { method: 'POST', body: reportedNrs === null ? {} : { reported_nrs: reportedNrs } },
      );
      setRecording(analysed);
      setStage('ANALYSED');
      if (analysed.analyses[0]) onAnalysis?.(analysed.analyses[0], analysed);
      try {
        setTrace(
          await request<SignalWaveform>(
            `/api/signals/recordings/${recording.id}/waveform?points=900`,
          ),
        );
      } catch {
        // A missing trace does not invalidate the analysis; the report still stands.
        setTrace(null);
      }
      history.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The analysis could not be completed.');
      setStage('UNAVAILABLE');
    } finally {
      setBusy(false);
    }
  }, [recording, reportedNrs, history, onAnalysis]);

  const reset = () => {
    setRecording(null);
    setTrace(null);
    setLive(null);
    setStage('READY');
    setError(null);
  };

  const analysis = recording?.analyses?.[0] ?? null;

  if (!patientId) {
    return (
      <Card className="p-5">
        <CardHead
          title="EEG and EMG"
          sub="Cortical and muscle activity, with a signal-quality gate of its own."
        />
        <p className="py-10 text-center text-[13px] text-mute">
          Choose a patient first — a recording is written against their file.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {reference.data && !reference.data.model_available && (
        <Card className="flex items-start gap-2.5 border-warn/30 bg-warn/8 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div>
            <p className="text-[13px] font-semibold text-ink">{reference.data.model_message}</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-soft">
              Recording, signal-quality assessment and feature extraction all work. Only the
              pain estimate requires a trained model, and none is registered.
            </p>
          </div>
        </Card>
      )}

      {reference.data && (
        <p className="rounded-[10px] bg-sunken px-4 py-2.5 text-[11.5px] leading-relaxed text-mute">
          {reference.data.notice}
        </p>
      )}

      {error && (
        <Card className="flex items-start gap-2.5 border-danger/30 bg-danger/8 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p className="text-[12px] leading-relaxed text-soft">{error}</p>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="space-y-4 p-4">
          <CardHead
            title="Session"
            action={
              <Pill tone={STAGE_TONE[stage]} size="xs" dot={stage === 'RECORDING'}>
                {STAGE_LABEL[stage]}
              </Pill>
            }
          />

          <div className="space-y-2 rounded-[10px] border border-hairline bg-sunken p-3">
            <Toggle
              checked={simulate}
              onChange={(value) => stage !== 'RECORDING' && setSimulate(value)}
              label="Simulation mode"
            />
            <p className="text-[11px] leading-relaxed text-faint">
              {simulate
                ? 'Simulation mode: samples are generated by the software simulator, not measured from anyone. Every record is stored and shown as SIMULATION and is never mixed with hardware data.'
                : 'Off: samples must be relayed from a connected amplifier. Nothing is recorded until they arrive.'}
            </p>
          </div>

          {!simulate && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="block text-xs font-medium text-soft">Acquisition device</span>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RefreshCw className="h-3 w-3" />}
                  disabled={stage === 'RECORDING'}
                  onClick={() => scan.reload()}
                >
                  Scan
                </Button>
              </div>
              {scan.data?.devices.length === 0 ? (
                <div className="rounded-[10px] border border-hairline bg-sunken px-3 py-2.5">
                  <p className="flex items-center gap-1.5 text-[12px] font-medium text-soft">
                    <Usb className="h-3.5 w-3.5" />
                    Device not connected
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-faint">
                    No amplifier was found on a serial bus or over BLE. Attach one and scan
                    again, or relay samples from a client that owns the device. Supported:{' '}
                    {(scan.data?.adapters ?? []).map((adapter) => adapter.label).join(', ')}.
                  </p>
                </div>
              ) : (
                <Select
                  label="Relayed by this client"
                  className="w-full [&>button]:w-full"
                  clearable
                  options={(scan.data?.devices ?? []).map((candidate) => ({
                    value: `${candidate.adapter}:${candidate.identifier}`,
                    label: candidate.label,
                    hint: `${candidate.sample_rate_hz} Hz${candidate.confirmed ? '' : ' · unconfirmed'}`,
                  }))}
                  value={device}
                  onChange={setDevice}
                />
              )}
            </div>
          )}

          <TextField
            label="EMG sampling rate"
            type="number"
            min={100}
            max={20000}
            step={50}
            value={emgRate}
            disabled={stage === 'RECORDING'}
            onChange={(event) => setEmgRate(event.target.value)}
            trailing={<span className="text-[11px] text-faint">Hz</span>}
            hint="Surface EMG is recorded on its own clock; its power extends past 250 Hz, well above what an EEG rate can carry."
          />

          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-soft">Channels</span>
            <div className="space-y-1">
              {channels.map((channel) => {
                const on = selected.includes(channel.code);
                return (
                  <button
                    key={channel.code}
                    type="button"
                    disabled={stage === 'RECORDING'}
                    onClick={() =>
                      setSelected((current) =>
                        current.includes(channel.code)
                          ? current.filter((code) => code !== channel.code)
                          : [...current, channel.code],
                      )
                    }
                    className={cx(
                      'flex w-full items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-left text-[12px] transition-colors disabled:opacity-50',
                      on
                        ? 'border-accent-edge bg-accent-wash text-accent-ink'
                        : 'border-hairline text-mute hover:border-hairline-strong',
                    )}
                  >
                    <span className="truncate">{channel.label}</span>
                    <span className="shrink-0 text-[10px] uppercase tracking-wide text-faint">
                      {channel.primary ? channel.modality : `${channel.modality} · optional`}
                    </span>
                  </button>
                );
              })}
            </div>
            {!primaryChosen && channels.length > 0 && (
              <p className="text-[11px] text-warn">
                Select at least one EEG or EMG channel — the analysis is of those.
              </p>
            )}
          </div>

          <p className="rounded-[10px] bg-sunken px-3 py-2 text-[11px] leading-relaxed text-faint">
            {reportedNrs === null
              ? 'No reported score yet. Record one on the Intensity step and it is stored beside the analysis — never used as an input to it.'
              : `The reported score of ${reportedNrs}/10 is stored beside the analysis and never used as an input to it.`}
          </p>

          <div className="flex flex-wrap gap-2">
            {stage !== 'RECORDING' && stage !== 'PROCESSING' && (
              <Button
                variant="primary"
                className="flex-1"
                icon={<Play className="h-4 w-4" />}
                disabled={!canStart}
                onClick={() => void start()}
              >
                Start recording
              </Button>
            )}
            {stage === 'RECORDING' && (
              <Button
                variant="danger"
                className="flex-1"
                icon={<CircleStop className="h-4 w-4" />}
                disabled={busy}
                onClick={() => void stop()}
              >
                Stop and save
              </Button>
            )}
            {stage === 'SAVED' && (
              <Button
                variant="primary"
                className="flex-1"
                icon={<Microscope className="h-4 w-4" />}
                disabled={busy}
                onClick={() => void analyse()}
              >
                Analyse recording
              </Button>
            )}
            {(stage === 'SAVED' || stage === 'ANALYSED' || stage === 'UNAVAILABLE') && (
              <Button icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={reset}>
                New session
              </Button>
            )}
          </div>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {stage === 'RECORDING' && recording && (
            <Card className="space-y-3 p-4">
              <CardHead
                title={
                  <span className="flex items-center gap-2">
                    <Radio className="h-4 w-4 animate-pulse text-danger" />
                    Recording
                    {recording.source === 'SIMULATION' && (
                      <Pill tone="warn" size="xs">simulation</Pill>
                    )}
                  </span>
                }
                action={
                  <span className="text-[20px] font-semibold text-ink tabular-nums">
                    {clock(
                      live
                        ? live.progress.elapsed_seconds
                        : (Date.now() - new Date(recording.started_at).getTime()) / 1000,
                    )}
                  </span>
                }
              />
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Figure label="Source" value={recording.source} />
                <Figure label="Device" value={recording.device_label ?? 'relayed by client'} />
                <Figure
                  label="Rates"
                  value={
                    Object.keys(recording.channel_rates ?? {}).length
                      ? [...new Set(Object.values(recording.channel_rates))]
                          .sort((a, b) => a - b)
                          .map((rate) => `${rate} Hz`)
                          .join(' / ')
                      : `${recording.sample_rate_hz} Hz`
                  }
                />
                <Figure
                  label="Samples written"
                  value={(live?.progress.samples ?? recording.samples).toLocaleString()}
                />
                <Figure label="Dropped" value={live?.progress.dropped_samples ?? 0} />
                <Figure label="Invalid frames" value={live?.progress.invalid_packets ?? 0} />
                <Figure label="Reconnects" value={live?.progress.reconnects ?? 0} />
                <Figure
                  label="Storage"
                  value={
                    live?.progress.error
                      ? 'failing'
                      : `${(live?.progress.rows_written ?? 0).toLocaleString()} rows`
                  }
                />
              </div>

              {live?.progress.error && (
                <p className="rounded-[10px] border border-danger/25 bg-danger/8 px-2.5 py-1.5 text-[11px] text-danger">
                  {live.progress.error}
                </p>
              )}
              {live?.progress.stalled_for_seconds != null &&
                live.progress.stalled_for_seconds > 3 && (
                  <p className="rounded-[10px] border border-warn/25 bg-warn/8 px-2.5 py-1.5 text-[11px] text-warn">
                    No samples for {live.progress.stalled_for_seconds.toFixed(0)} s. The device
                    is connected but producing nothing.
                  </p>
                )}

              {live?.channels && Object.keys(live.channels).length > 0 && (
                <div className="space-y-2 border-t border-hairline pt-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-soft">Live traces</span>
                    <span className="text-[11px] text-faint">
                      {live.decimation}× decimated for display
                    </span>
                  </div>
                  {Object.entries(live.channels).map(([code, values]) => (
                    <Trace
                      key={code}
                      values={values}
                      label={`${byCode[code]?.label ?? code} · ${live.rates[code] ?? '?'} Hz`}
                      unit={byCode[code]?.unit ?? ''}
                      tone={MODALITY_COLOUR[byCode[code]?.modality ?? ''] ?? '#94a3b8'}
                    />
                  ))}
                </div>
              )}

              <div className="space-y-1 border-t border-hairline pt-3">
                <span className="block text-xs font-medium text-soft">Sensor connection</span>
                <div className="flex flex-wrap gap-1.5">
                  {recording.channels.map((code) => (
                    <Pill key={String(code)} tone="ok" size="xs">
                      {byCode[String(code)]?.label ?? String(code)}
                    </Pill>
                  ))}
                </div>
                <p className="text-[11px] text-faint">
                  Connection as the acquisition reported it. Signal quality is measured when
                  the recording stops.
                </p>
              </div>
            </Card>
          )}

          {recording && (stage === 'SAVED' || stage === 'ANALYSED') && (
            <Card className="space-y-2 p-4">
              <CardHead title="Recording saved" />
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Figure
                  label="Duration"
                  value={
                    recording.duration_seconds ? `${recording.duration_seconds.toFixed(1)} s` : '—'
                  }
                />
                <Figure label="Samples" value={recording.samples.toLocaleString()} />
                <Figure label="Dropped" value={recording.dropped_samples} />
                <Figure
                  label="Files intact"
                  value={recording.validation?.intact ? 'yes' : 'see findings'}
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {recording.files.map((file) => (
                  <Pill key={String(file.name)} size="xs" title={`sha256 ${file.sha256}`}>
                    {String(file.name)} · {bytes(file.bytes as number)}
                  </Pill>
                ))}
              </div>
              {((recording.validation?.findings as string[]) ?? []).map((finding) => (
                <p key={finding} className="text-[11px] text-warn">
                  {finding}
                </p>
              ))}
              {stage === 'SAVED' && (
                <p className="text-[11px] text-faint">
                  The recording is written and validated. Analysing reads it back, assesses
                  signal quality and extracts features.
                </p>
              )}
            </Card>
          )}

          {analysis && recording && (
            <Report recording={recording} analysis={analysis} trace={trace} byCode={byCode} />
          )}

          {stage === 'READY' && !analysis && (
            <Card className="px-6 py-12 text-center">
              <Activity className="mx-auto mb-2 h-6 w-6 text-faint" />
              <p className="text-[13px] text-mute">
                Choose channels and start a session. Nothing is written until samples arrive.
              </p>
            </Card>
          )}
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 border-b border-hairline p-4">
          <History className="h-4 w-4 text-faint" />
          <h3 className="text-[13px] font-semibold text-ink">
            Earlier recordings for this patient
          </h3>
          <span className="ml-auto text-[11px] text-mute">
            {history.data ? `${history.data.length} session(s)` : ''}
          </span>
        </div>
        {history.loading ? (
          <p className="px-4 py-8 text-center text-[13px] text-mute">Loading…</p>
        ) : (history.data ?? []).length === 0 ? (
          <p className="px-4 py-8 text-center text-[13px] text-mute">
            No recording has been made for this patient yet.
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {history.data?.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[12px]"
              >
                <span className="text-mute">{when(row.started_at)}</span>
                <span className="text-soft tabular-nums">
                  {row.duration_seconds ? `${row.duration_seconds.toFixed(1)} s` : '—'}
                </span>
                <Pill tone={row.source === 'SIMULATION' ? 'warn' : 'ok'} size="xs">
                  {row.source.toLowerCase()}
                </Pill>
                <span className="text-mute">{row.channels.length} channels</span>
                {row.quality_verdict && (
                  <Pill tone={QUALITY_TONE[row.quality_verdict]} size="xs">
                    signal {row.quality_verdict.toLowerCase()}
                  </Pill>
                )}
                <span className="ml-auto text-mute">
                  {row.state.toLowerCase().replace(/_/g, ' ')}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
};

const Figure: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="rounded-lg bg-sunken px-2.5 py-2">
    <div className="eyebrow">{label}</div>
    <div className="truncate text-[12px] font-semibold text-ink">{value}</div>
  </div>
);

const Report: React.FC<{
  recording: SignalRecordingDetail;
  analysis: SignalAnalysis;
  trace: SignalWaveform | null;
  byCode: Record<string, ChannelInfo>;
}> = ({ recording, analysis, trace, byCode }) => {
  const quality =
    recording.quality && 'verdict' in recording.quality
      ? (recording.quality as {
          verdict: QualityVerdict;
          findings: string[];
          channels: { channel: string; verdict: QualityVerdict; findings: string[] }[];
        })
      : null;

  return (
    <Card className="space-y-5 p-4">
      <CardHead
        title="Analysis report"
        action={
          <div className="flex flex-wrap gap-1.5">
            <Pill tone={recording.source === 'SIMULATION' ? 'warn' : 'ok'} size="xs">
              {recording.source.toLowerCase()}
            </Pill>
            {recording.quality_verdict && (
              <Pill tone={QUALITY_TONE[recording.quality_verdict]} size="xs">
                signal {recording.quality_verdict.toLowerCase()}
              </Pill>
            )}
          </div>
        }
      />

      {/* The two scores, side by side and never merged. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[10px] border border-accent-edge bg-accent-wash p-4">
          <div className="eyebrow">Patient-reported pain</div>
          <div className="mt-1 text-[28px] font-semibold text-ink tabular-nums">
            {analysis.reported_nrs ?? '—'}
            {analysis.reported_nrs !== null && (
              <span className="text-[15px] font-normal text-mute">/10</span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-mute">
            The patient's own score. Not an input to any estimate.
          </p>
        </div>

        <div
          className={cx(
            'rounded-[10px] border p-4',
            analysis.estimate_available
              ? 'border-ok/25 bg-ok/8'
              : 'border-warn/25 bg-warn/8',
          )}
        >
          <div className="eyebrow">Signal estimate</div>
          {analysis.estimate_available ? (
            <>
              <div className="mt-1 text-[28px] font-semibold text-ink tabular-nums">
                {analysis.pain_score?.toFixed(1)}
              </div>
              {/* The scale, not a hardcoded /10. The signal model is fitted on whichever
                  corpus is available and a corpus rates pain on its own scale. */}
              <p className="mt-0.5 text-[11px] text-mute">
                {[analysis.pain_category, analysis.scale].filter(Boolean).join(' · ')}
                {analysis.interval_low !== null && analysis.interval_high !== null && (
                  <> · interval {analysis.interval_low}–{analysis.interval_high}</>
                )}
              </p>
            </>
          ) : (
            <p className="mt-1 text-[12px] leading-relaxed text-soft">
              {analysis.unavailable_reason}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Figure
          label="Duration"
          value={recording.duration_seconds ? `${recording.duration_seconds.toFixed(1)} s` : '—'}
        />
        <Figure label="Features" value={analysis.feature_count} />
        <Figure
          label="Heart rate"
          value={analysis.heart_rate_bpm ? `${analysis.heart_rate_bpm} bpm` : 'not available'}
        />
        <Figure
          label="HRV (RMSSD)"
          value={analysis.hrv_rmssd_ms ? `${analysis.hrv_rmssd_ms} ms` : 'not available'}
        />
        <Figure
          label="Skin conductance"
          value={
            analysis.skin_conductance_us ? `${analysis.skin_conductance_us} µS` : 'not available'
          }
        />
        <Figure
          label="Respiration"
          value={
            analysis.respiration_per_min ? `${analysis.respiration_per_min}/min` : 'not available'
          }
        />
        <Figure label="Model" value={analysis.model_version ?? 'none'} />
        <Figure
          label="Uncertainty"
          value={analysis.uncertainty !== null ? analysis.uncertainty : 'not available'}
        />
        <Figure label="Stored" value={bytes(recording.bytes)} />
        <Figure label="Analysed" value={when(analysis.analysed_at)} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Metrics title="EEG" values={analysis.summary.eeg} />
        <Metrics title="EMG" values={analysis.summary.emg} />
      </div>

      {quality && (
        <div className="space-y-1.5">
          <h4 className="text-[13px] font-semibold text-ink">Signal quality by channel</h4>
          <div className="space-y-1">
            {quality.channels.map((channel) => (
              <div
                key={channel.channel}
                className="flex flex-wrap items-center gap-2 rounded-[10px] border border-hairline bg-sunken px-2.5 py-1.5"
              >
                <Pill tone={QUALITY_TONE[channel.verdict]} size="xs">
                  {channel.verdict.toLowerCase()}
                </Pill>
                <span className="text-[12px] text-soft">
                  {byCode[channel.channel]?.label ?? channel.channel}
                </span>
                {channel.findings.length > 0 && (
                  <span className="min-w-0 flex-1 text-[11px] text-mute">
                    {channel.findings[0]}
                  </span>
                )}
              </div>
            ))}
          </div>
          {quality.findings.map((finding) => (
            <p key={finding} className="text-[11px] text-warn">
              {finding}
            </p>
          ))}
        </div>
      )}

      {trace && (
        <div className="space-y-2">
          <h4 className="text-[13px] font-semibold text-ink">Recorded traces</h4>
          {Object.entries(trace.channels).map(([code, values]) => (
            <Trace
              key={code}
              values={values}
              label={byCode[code]?.label ?? code}
              unit={byCode[code]?.unit ?? ''}
              tone={MODALITY_COLOUR[byCode[code]?.modality ?? ''] ?? '#94a3b8'}
            />
          ))}
          <p className="text-[11px] text-faint">{trace.notice}</p>
        </div>
      )}

      {analysis.notes.length > 0 && (
        <ul className="space-y-1 border-t border-hairline pt-3">
          {analysis.notes.map((note) => (
            <li key={String(note)} className="text-[11px] leading-relaxed text-faint">
              {String(note)}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
};

const Metrics: React.FC<{ title: string; values: Record<string, number | null> }> = ({
  title,
  values,
}) => {
  const present = Object.entries(values ?? {}).filter(([, value]) => value !== null);
  return (
    <div className="rounded-[10px] border border-hairline bg-sunken p-3">
      <h4 className="mb-2 text-[13px] font-semibold text-ink">{title} analysis</h4>
      {present.length === 0 ? (
        <p className="text-[11px] text-mute">
          No {title} feature was derived; see the per-channel quality above.
        </p>
      ) : (
        <dl className="space-y-1">
          {present.map(([name, value]) => (
            <div key={name} className="flex items-baseline justify-between gap-2 text-[12px]">
              <dt className="truncate text-mute">{name.replace(/_/g, ' ')}</dt>
              <dd className="shrink-0 text-soft tabular-nums">
                {typeof value === 'number' ? value.toFixed(3) : '—'}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
};
