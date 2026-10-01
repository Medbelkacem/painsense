import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Camera, CameraOff, CircleStop, Eye, Lock, Mic, MicOff, RefreshCw,
  ShieldCheck, SwitchCamera, Trash2, Upload,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type {
  BehaviourMeasure, BehaviourObservation, BehaviourReference, QualityVerdict, RestingBehaviour,
} from '../api/types';
import { useAudioLevel } from './useAudioLevel';
import { useClipRecorder } from './useClipRecorder';
import { useMediaCapture, type CaptureKind } from './useMediaCapture';
import { Button } from '../ui/Button';
import { Card, CardHead } from '../ui/Card';
import { Select } from '../ui/Dropdown';
import { Toggle } from '../ui/Field';
import { Pill, type Tone } from '../ui/Pill';
import { Segmented } from '../ui/Segmented';
import { cx } from '../lib/cx';

const QUALITY_TONE: Record<QualityVerdict, Tone> = {
  GOOD: 'ok',
  ADEQUATE: 'teal',
  POOR: 'warn',
  UNUSABLE: 'danger',
};

/** Clip lengths offered. The shortest is the floor the measures need behind them. */
const LENGTHS = [10, 20, 30];
const DEFAULT_LENGTH = 20;

/** How each measure is rendered: its decimals, and whether to show it as a percentage. */
const FORMATS: Record<string, { decimals: number; percent?: boolean }> = {
  eye_aperture_ratio: { decimals: 2 },
  eye_squint_index: { decimals: 0, percent: true },
  eye_open_share: { decimals: 0, percent: true },
  eye_asymmetry_ratio: { decimals: 2 },
  blink_rate_per_min: { decimals: 1 },
  blink_closure_ms: { decimals: 0 },
  long_closure_share: { decimals: 0, percent: true },
  pupil_diameter_mm: { decimals: 2 },
  pupil_iris_ratio: { decimals: 2 },
  pupil_unrest_mm: { decimals: 2 },
  pupil_asymmetry_mm: { decimals: 2 },
  gaze_dispersion_ratio: { decimals: 3 },
  brow_gap_ratio: { decimals: 3 },
  brow_lower_index: { decimals: 0, percent: true },
  mouth_open_ratio: { decimals: 3 },
  face_motion_index: { decimals: 3 },
  head_turn_share: { decimals: 0, percent: true },
  facial_action_index: { decimals: 0, percent: true },
  f0_mean_hz: { decimals: 1 },
  f0_sd_semitones: { decimals: 2 },
  jitter_percent: { decimals: 2 },
  shimmer_percent: { decimals: 2 },
  hnr_db: { decimals: 1 },
  intensity_db: { decimals: 1 },
  voiced_share: { decimals: 0, percent: true },
  pause_share: { decimals: 0, percent: true },
  speech_rate_per_s: { decimals: 2 },
  vocalisation_share: { decimals: 0, percent: true },
  spectral_centroid_hz: { decimals: 0 },
  spectral_rolloff_hz: { decimals: 0 },
  zero_crossing_rate: { decimals: 3 },
};

/** The eye measures, in the order a clinician reads them. The camera is pointed here. */
const EYE_ORDER = [
  'eye_open_share', 'eye_aperture_ratio', 'eye_squint_index', 'blink_rate_per_min',
  'blink_closure_ms', 'long_closure_share', 'pupil_diameter_mm', 'pupil_unrest_mm',
  'pupil_asymmetry_mm', 'gaze_dispersion_ratio', 'eye_asymmetry_ratio',
];
const FACE_ORDER = [
  'facial_action_index', 'brow_lower_index', 'brow_gap_ratio', 'mouth_open_ratio',
  'face_motion_index', 'head_turn_share',
];
const VOICE_ORDER = [
  'f0_mean_hz', 'f0_sd_semitones', 'jitter_percent', 'shimmer_percent', 'hnr_db',
  'intensity_db', 'voiced_share', 'pause_share', 'speech_rate_per_s', 'vocalisation_share',
];

function show(code: string, value: number): string {
  const format = FORMATS[code] ?? { decimals: 2 };
  if (format.percent) return `${(value * 100).toFixed(format.decimals)}%`;
  return value.toFixed(format.decimals);
}

interface BehaviourPanelProps {
  /** Null while no patient is chosen; the panel then explains itself and does nothing. */
  patientId: string | null;
  /** Ties the observation to the assessment being recorded. */
  assessmentId?: string | null;
  onObservation?: (observation: BehaviourObservation) => void;
}

/**
 * Camera and microphone measurement.
 *
 * Records a short clip and sends it to be measured. What comes back is a table of numbers
 * about behaviour — how open the eyes were, how often they closed, what the pupils were
 * doing, where the brow sat, how the voice sounded — and the panel's job is to show those
 * numbers with the sentence that keeps each of them from being read as a pain reading.
 *
 * Four rules it keeps.
 *
 * **Consent is recorded before the browser is asked.** Not a checkbox here: a row in the
 * patient's record, under one named scope, which the server resolves before it decodes
 * anything. The browser's own permission dialog comes after, and cannot be bypassed.
 *
 * **The instruction is on screen while the camera is live.** The eye measures are taken
 * only from frames where both eyes are found open, so the patient has to be looking at the
 * lens with their eyes open, and the person operating the camera has to be told that while
 * it matters rather than afterwards.
 *
 * **The clip is not kept unless somebody asks.** The default is that it is measured and
 * deleted, and the panel says so where the decision is made.
 *
 * **Nothing absent is shown as a zero.** A measure the clip did not support is listed with
 * the reason it is missing, in its own panel, because "the patient never opened their eyes"
 * and "the patient's eyes were barely open" are different findings.
 */
export const BehaviourPanel: React.FC<BehaviourPanelProps> = ({
  patientId,
  assessmentId = null,
  onObservation,
}) => {
  const capture = useMediaCapture();
  const audio = useAudioLevel(capture.stream);
  const recorder = useClipRecorder(capture.stream);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const [kind, setKind] = useState<CaptureKind>('both');
  const [cameraId, setCameraId] = useState<string | null>(null);
  const [microphoneId, setMicrophoneId] = useState<string | null>(null);
  const [length, setLength] = useState(DEFAULT_LENGTH);
  const [atRest, setAtRest] = useState(false);
  const [keepClip, setKeepClip] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [observation, setObservation] = useState<BehaviourObservation | null>(null);

  const reference = useQuery<BehaviourReference>('/api/behaviour/reference');
  const consent = useQuery<{ granted: boolean; withdrawn_at: string | null } | null>(
    patientId ? `/api/behaviour/patients/${patientId}/consent` : null,
  );
  const resting = useQuery<RestingBehaviour>(
    patientId ? `/api/behaviour/patients/${patientId}/resting` : null,
  );

  const byCode = useMemo(
    () => new Map((reference.data?.measures ?? []).map((entry) => [entry.code, entry])),
    [reference.data],
  );

  const consented = consent.data?.granted === true && !consent.data?.withdrawn_at;
  const live = capture.status === 'live';
  const hasVideo = Boolean(capture.stream?.getVideoTracks().length);
  const hasAudio = Boolean(capture.stream?.getAudioTracks().length);
  const insecure = capture.status === 'insecure';

  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;
    element.srcObject = capture.stream;
    if (capture.stream) void element.play().catch(() => undefined);
  }, [capture.stream]);

  const grant = useCallback(
    async (granted: boolean) => {
      if (!patientId) return;
      setFailure(null);
      try {
        await request(`/api/behaviour/patients/${patientId}/consent`, {
          method: 'PUT',
          body: { granted },
        });
        consent.reload();
      } catch (cause) {
        setFailure(cause instanceof ApiError ? cause.message : 'The consent was not recorded.');
      }
    },
    [consent, patientId],
  );

  const begin = useCallback(() => {
    void capture.start(kind, {
      cameraId: cameraId ?? undefined,
      microphoneId: microphoneId ?? undefined,
      facing: capture.facing,
    });
  }, [capture, kind, cameraId, microphoneId]);

  const flip = useCallback(() => {
    const facing = capture.facing === 'user' ? 'environment' : 'user';
    // Clearing the explicit camera id matters: a deviceId constraint wins over facingMode,
    // so flipping would silently do nothing while a specific camera is selected.
    setCameraId(null);
    void capture.start(kind, { microphoneId: microphoneId ?? undefined, facing });
  }, [capture, kind, microphoneId]);

  const submit = useCallback(async () => {
    const clip = recorder.clip;
    if (!clip || !patientId) return;
    setBusy(true);
    setFailure(null);
    try {
      const form = new FormData();
      form.append('clip', clip.blob, 'clip.webm');
      form.append('at_rest', String(atRest));
      form.append('retain_media', String(keepClip));
      if (assessmentId) form.append('assessment_id', assessmentId);
      const measured = await request<BehaviourObservation>(
        `/api/behaviour/patients/${patientId}/observations`,
        { method: 'POST', body: form },
      );
      setObservation(measured);
      onObservation?.(measured);
      recorder.discard();
      resting.reload();
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The clip could not be measured.');
    } finally {
      setBusy(false);
    }
  }, [assessmentId, atRest, keepClip, onObservation, patientId, recorder, resting]);

  const canRecord = live && consented && recorder.status !== 'recording';

  if (!patientId) {
    return (
      <Card className="p-5">
        <CardHead
          title="Camera and microphone"
          sub="Measures the eyes, the face and the voice from a short clip."
        />
        <p className="py-10 text-center text-[13px] text-mute">
          Choose a patient first. Consent is recorded against their file before any device
          is opened.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {reference.data && (
        <Card className="flex items-start gap-2.5 p-4">
          <Eye className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <div className="space-y-1">
            <p className="text-[13px] font-medium text-ink">{reference.data.instruction}</p>
            <p className="text-[11.5px] leading-relaxed text-mute">{reference.data.notice}</p>
          </div>
        </Card>
      )}

      {insecure && (
        <Card className="flex items-start gap-2.5 border-warn/30 bg-warn/8 p-4">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div>
            <p className="text-[13px] font-semibold text-ink">This page is not a secure context</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-soft">{capture.error}</p>
          </div>
        </Card>
      )}

      {(capture.error && !insecure) || recorder.error || failure ? (
        <Card className="flex items-start gap-2.5 border-danger/30 bg-danger/8 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p className="text-[12px] leading-relaxed text-soft">
            {failure ?? recorder.error ?? capture.error}
          </p>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          <Card className="space-y-3 p-4">
            <CardHead title="Consent" sub="Held against the patient's file, under one scope." />
            {consent.data === null && (
              <div className="space-y-2 rounded-[10px] border border-warn/30 bg-warn/8 px-3 py-2.5">
                <p className="text-[11px] leading-relaxed text-soft">
                  No consent is on record for recording this patient's camera and microphone.
                  Nothing is decoded without one — the server refuses the clip before it reads
                  it.
                </p>
                <Button variant="primary" size="sm" className="w-full" onClick={() => void grant(true)}>
                  Record consent for this patient
                </Button>
              </div>
            )}
            {consented && (
              <div className="flex items-start justify-between gap-2 rounded-[10px] border border-ok/25 bg-ok/8 px-3 py-2.5">
                <p className="text-[11px] leading-relaxed text-soft">
                  Consent is on record. The browser will ask for permission separately.
                </p>
                <button
                  type="button"
                  onClick={() => void grant(false)}
                  className="shrink-0 text-[11px] font-medium text-mute underline hover:text-ink"
                >
                  withdraw
                </button>
              </div>
            )}
            {consent.data && !consented && (
              <div className="space-y-2 rounded-[10px] border border-danger/30 bg-danger/8 px-3 py-2.5">
                <p className="text-[11px] leading-relaxed text-soft">
                  Consent was withdrawn. Clips already measured keep their numbers; no new one
                  will be decoded.
                </p>
                <Button size="sm" className="w-full" onClick={() => void grant(true)}>
                  Record consent again
                </Button>
              </div>
            )}

            {resting.data?.recorded_at && (
              <p className="rounded-[10px] bg-sunken px-3 py-2 text-[11px] leading-relaxed text-mute">
                A resting observation exists for this patient, so orbital tightening and brow
                lowering are read against them rather than against their widest moment in the
                clip.
              </p>
            )}
            {resting.data && !resting.data.recorded_at && (
              <p className="rounded-[10px] bg-sunken px-3 py-2 text-[11px] leading-relaxed text-mute">
                No resting observation for this patient. Record one with them settled — tick
                “at rest” below — and every later clip can be compared with it.
              </p>
            )}
          </Card>

          <Card className="space-y-4 p-4">
            <CardHead title="What to record" />
            <div className="space-y-1.5">
              <span className="block text-xs font-medium text-soft">Devices</span>
              <Segmented
                options={[
                  { value: 'both', label: 'Both' },
                  { value: 'camera', label: 'Camera' },
                  { value: 'microphone', label: 'Mic' },
                ]}
                value={kind}
                onChange={(value) => !live && setKind(value as CaptureKind)}
              />
            </div>

            <div className="space-y-1.5">
              <span className="block text-xs font-medium text-soft">Clip length</span>
              <Segmented
                options={LENGTHS.map((option) => ({ value: String(option), label: `${option}s` }))}
                value={String(length)}
                onChange={(value) =>
                  recorder.status !== 'recording' && setLength(Number(value))
                }
              />
              {reference.data && length < reference.data.minimum_seconds && (
                <p className="text-[11px] text-warn">
                  Under {reference.data.minimum_seconds}s a blink rate has too few blinks
                  behind it to quote.
                </p>
              )}
            </div>

            {capture.cameras.length > 0 && kind !== 'microphone' && (
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-soft">Camera</span>
                <Select
                  label={`Default (${capture.facing === 'user' ? 'front' : 'rear'})`}
                  className="w-full [&>button]:w-full"
                  clearable
                  options={capture.cameras.map((device) => ({
                    value: device.deviceId,
                    label: device.label,
                  }))}
                  value={cameraId}
                  onChange={setCameraId}
                />
              </div>
            )}
            {capture.microphones.length > 0 && kind !== 'camera' && (
              <div className="space-y-1.5">
                <span className="block text-xs font-medium text-soft">Microphone</span>
                <Select
                  label="Default"
                  className="w-full [&>button]:w-full"
                  clearable
                  options={capture.microphones.map((device) => ({
                    value: device.deviceId,
                    label: device.label,
                  }))}
                  value={microphoneId}
                  onChange={setMicrophoneId}
                />
              </div>
            )}

            <div className="space-y-3 border-t border-hairline pt-3">
              <div>
                <Toggle checked={atRest} onChange={setAtRest} label="Recorded at rest" />
                <p className="mt-1 text-[11px] leading-relaxed text-faint">
                  Becomes this patient's reference rather than a reading. Record one once,
                  with the patient settled.
                </p>
              </div>
              <div>
                <Toggle checked={keepClip} onChange={setKeepClip} label="Keep the clip" />
                <p className="mt-1 text-[11px] leading-relaxed text-faint">
                  Off by default. The clip is measured and deleted; only the numbers are
                  stored. Kept clips are encrypted and can be deleted later.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {!live ? (
                <Button
                  variant="primary"
                  className="flex-1"
                  icon={<Camera className="h-4 w-4" />}
                  disabled={!consented || capture.status === 'requesting'}
                  onClick={begin}
                >
                  {capture.status === 'requesting' ? 'Asking…' : 'Open devices'}
                </Button>
              ) : (
                <Button
                  className="flex-1"
                  icon={<CircleStop className="h-4 w-4" />}
                  onClick={capture.stop}
                >
                  Close devices
                </Button>
              )}
              <Button
                size="md"
                icon={<RefreshCw className="h-3.5 w-3.5" />}
                onClick={capture.refreshDevices}
              >
                Devices
              </Button>
            </div>
            {!consented && (
              <p className="text-[11px] text-faint">
                Record the patient's consent above to enable the camera.
              </p>
            )}
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <Card className="space-y-3 p-4">
            <CardHead
              title={
                <span className="flex items-center gap-2">
                  {hasVideo ? (
                    <Camera className="h-4 w-4 text-accent" />
                  ) : (
                    <CameraOff className="h-4 w-4 text-faint" />
                  )}
                  Preview
                </span>
              }
              action={
                <div className="flex items-center gap-2">
                  {recorder.status === 'recording' && (
                    <Pill tone="danger" size="xs" dot>
                      Recording — {recorder.remaining}s left
                    </Pill>
                  )}
                  {live && recorder.status !== 'recording' && (
                    <Pill tone="warn" size="xs" dot>
                      {hasVideo && hasAudio
                        ? 'Camera and microphone live'
                        : hasVideo
                          ? 'Camera live'
                          : 'Microphone live'}
                    </Pill>
                  )}
                  {live && hasVideo && (
                    <Button
                      size="sm"
                      icon={<SwitchCamera className="h-3.5 w-3.5" />}
                      onClick={flip}
                    >
                      {capture.facing === 'user' ? 'Rear' : 'Front'}
                    </Button>
                  )}
                </div>
              }
            />

            <div className="relative overflow-hidden rounded-[10px] border border-hairline bg-sunken">
              <video
                ref={videoRef}
                playsInline
                muted
                autoPlay
                className={cx(
                  'aspect-video w-full object-cover',
                  capture.facing === 'user' && 'scale-x-[-1]',
                  !hasVideo && 'hidden',
                )}
              />
              {!hasVideo && (
                <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 text-faint">
                  <CameraOff className="h-7 w-7" />
                  <span className="text-[11.5px]">
                    {live ? 'Microphone only — no camera in this session' : 'Camera not open'}
                  </span>
                </div>
              )}
              {live && hasVideo && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-3 pb-2.5 pt-8">
                  <p className="flex items-center gap-1.5 text-[12px] font-semibold text-white">
                    <Eye className="h-3.5 w-3.5" />
                    Eyes open, looking at the lens
                  </p>
                  <p className="text-[11px] leading-snug text-white/75">
                    The eye measures come only from frames where both eyes are found open.
                  </p>
                </div>
              )}
              {recorder.status === 'recording' && (
                <span className="absolute left-2 top-2 flex items-center gap-1.5 rounded bg-danger px-2 py-0.5 text-[10px] font-bold text-white">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
                  REC {recorder.remaining}s
                </span>
              )}
            </div>

            {capture.settings && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Figure
                  label="Resolution"
                  value={
                    capture.settings.width
                      ? `${capture.settings.width}×${capture.settings.height}`
                      : '—'
                  }
                />
                <Figure
                  label="Frame rate"
                  value={
                    capture.settings.frameRate
                      ? `${Math.round(capture.settings.frameRate)} fps`
                      : '—'
                  }
                />
                <Figure
                  label="Audio rate"
                  value={capture.settings.sampleRate ? `${capture.settings.sampleRate} Hz` : '—'}
                />
                <Figure label="Facing" value={capture.facing === 'user' ? 'front' : 'rear'} />
              </div>
            )}

            {hasAudio && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-soft">
                    <Mic className="h-3.5 w-3.5 text-violet" />
                    Microphone
                  </span>
                  {audio.clipping ? (
                    <Pill tone="danger" size="xs">clipping</Pill>
                  ) : audio.silent ? (
                    <Pill size="xs">silent</Pill>
                  ) : (
                    <Pill tone="ok" size="xs">picking up sound</Pill>
                  )}
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-sunken">
                  <div
                    className="h-full transition-[width] duration-75"
                    style={{
                      width: `${Math.min(100, Math.sqrt(audio.rms) * 140)}%`,
                      background: audio.clipping ? 'var(--danger)' : 'var(--violet)',
                    }}
                  />
                </div>
              </div>
            )}
            {live && !hasAudio && (
              <p className="flex items-center gap-1.5 text-[11px] text-faint">
                <MicOff className="h-3.5 w-3.5" />
                No microphone in this session — the voice measures will be absent.
              </p>
            )}

            <div className="border-t border-hairline pt-3">
              {recorder.status === 'recording' ? (
                <Button
                  variant="danger"
                  className="w-full"
                  icon={<CircleStop className="h-4 w-4" />}
                  onClick={recorder.stop}
                >
                  Stop early ({recorder.remaining}s left)
                </Button>
              ) : (
                <Button
                  variant="primary"
                  className="w-full"
                  disabled={!canRecord}
                  onClick={() => recorder.start(length)}
                  icon={<span className="h-2.5 w-2.5 rounded-full bg-current" />}
                >
                  Record {length}s
                </Button>
              )}
            </div>
          </Card>

          {recorder.clip && (
            <Card className="space-y-3 p-4">
              <CardHead
                title={`Recorded — ${recorder.clip.seconds}s`}
                sub={`${(recorder.clip.blob.size / 1e6).toFixed(1)} MB · ${recorder.clip.mediaType}`}
              />
              <video
                src={recorder.clip.url}
                controls
                className="aspect-video w-full rounded-[10px] border border-hairline bg-sunken"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  className="flex-1"
                  icon={<Upload className="h-4 w-4" />}
                  disabled={busy}
                  onClick={() => void submit()}
                >
                  {busy ? 'Measuring…' : atRest ? 'Measure and set as resting' : 'Measure'}
                </Button>
                <Button
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  disabled={busy}
                  onClick={recorder.discard}
                >
                  Discard
                </Button>
              </div>
              <p className="text-[11px] leading-relaxed text-faint">
                {keepClip
                  ? 'This clip will be kept, encrypted, and can be deleted later.'
                  : 'This clip will be deleted as soon as the measures are taken from it.'}
              </p>
            </Card>
          )}

          {observation && (
            <>
              <Card className="space-y-3 p-4">
                <CardHead
                  title="What the clip carried"
                  action={
                    observation.quality_verdict && (
                      <Pill tone={QUALITY_TONE[observation.quality_verdict as QualityVerdict]} size="xs">
                        quality {observation.quality_verdict.toLowerCase()}
                      </Pill>
                    )
                  }
                />
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Figure
                    label="Length"
                    value={
                      observation.duration_seconds
                        ? `${observation.duration_seconds.toFixed(1)}s`
                        : '—'
                    }
                  />
                  <Figure
                    label="Frames measured"
                    value={`${observation.frames_analysed} of ${observation.frames_decoded}`}
                  />
                  <Figure
                    label="Eye windows"
                    value={observation.eyes_calibrated ? 'fitted to this face' : 'average face'}
                  />
                  <Figure
                    label="Clip"
                    value={observation.media_retained ? 'kept, encrypted' : 'deleted'}
                  />
                </div>
                <div className="space-y-2">
                  {observation.modalities.map((entry) => (
                    <div
                      key={entry.modality}
                      className="rounded-[10px] border border-hairline bg-sunken px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[12px] font-medium capitalize text-soft">
                          {entry.modality.toLowerCase()}
                        </span>
                        <Pill tone={QUALITY_TONE[entry.verdict as QualityVerdict]} size="xs">
                          {entry.verdict.toLowerCase()}
                        </Pill>
                      </div>
                      {entry.findings.map((finding) => (
                        <p key={finding} className="mt-1 text-[11px] leading-relaxed text-mute">
                          {finding}
                        </p>
                      ))}
                    </div>
                  ))}
                </div>
              </Card>

              <MeasureGroup
                title="Eyes"
                icon={<Eye className="h-4 w-4 text-accent" />}
                order={EYE_ORDER}
                observation={observation}
                byCode={byCode}
              />
              <MeasureGroup
                title="Face"
                icon={<Camera className="h-4 w-4 text-teal" />}
                order={FACE_ORDER}
                observation={observation}
                byCode={byCode}
              />
              <MeasureGroup
                title="Voice"
                icon={<Mic className="h-4 w-4 text-violet" />}
                order={VOICE_ORDER}
                observation={observation}
                byCode={byCode}
              />

              {observation.voice_estimate && (
                <Card className="space-y-2 p-4">
                  <CardHead title="Voice model" />
                  {observation.voice_estimate.available ? (
                    <div className="flex items-baseline gap-3">
                      <span className="text-[22px] font-semibold text-ink">
                        {observation.voice_estimate.label}
                      </span>
                      <span className="text-[11.5px] text-mute tabular-nums">
                        level {observation.voice_estimate.level?.toFixed(2)} of{' '}
                        {observation.voice_estimate.scale.length}
                        {observation.voice_estimate.level_error !== null &&
                          ` · ±${observation.voice_estimate.level_error.toFixed(2)} levels`}
                      </span>
                    </div>
                  ) : (
                    <p className="text-[12px] leading-relaxed text-warn">
                      {observation.voice_estimate.message}
                    </p>
                  )}
                  {observation.voice_estimate.limitations.length > 0 && (
                    <ul className="space-y-1 border-t border-hairline pt-2">
                      {observation.voice_estimate.limitations.map((line) => (
                        <li key={line} className="text-[11px] leading-relaxed text-faint">
                          {line}
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              )}

              {Object.keys(observation.absent).length > 0 && (
                <Card className="space-y-2 p-4">
                  <CardHead
                    title="Not measured, and why"
                    sub="Absent rather than zero. A measure with nothing behind it would be read as a very small opening or a very quiet voice."
                  />
                  <div className="space-y-1">
                    {Object.entries(observation.absent).map(([code, reason]) => (
                      <div key={code} className="flex gap-2 text-[11px] leading-relaxed">
                        <span className="w-44 shrink-0 font-medium text-soft">
                          {byCode.get(code)?.label ?? code}
                        </span>
                        <span className="text-mute">{String(reason)}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {observation.notes.length > 0 && (
                <Card className="space-y-1.5 p-4">
                  <CardHead title="Notes" />
                  {observation.notes.map((note) => (
                    <p key={note} className="text-[11px] leading-relaxed text-mute">
                      {note}
                    </p>
                  ))}
                </Card>
              )}
            </>
          )}

          <Card className="flex items-start gap-2.5 p-4">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
            <p className="text-[11px] leading-relaxed text-mute">
              The clip is sent over the encrypted connection, measured, and deleted unless it
              was asked for. No face is matched against anything, nothing is transcribed, and
              the digest kept alongside the measures identifies nobody. Closing the devices
              releases the camera and microphone immediately, and so does leaving the step.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
};

const Figure: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="rounded-lg bg-sunken px-2.5 py-1.5">
    <div className="eyebrow">{label}</div>
    <div className="truncate text-[12px] font-semibold text-ink">{value}</div>
  </div>
);

/** One measured number, with its unit, its change from rest, and what else moves it. */
const Measure: React.FC<{
  measure: BehaviourMeasure;
  value: number;
  delta?: number;
  reference?: string;
  support?: number;
}> = ({ measure, value, delta, reference, support }) => (
  <div className="rounded-[10px] border border-hairline bg-sunken px-3 py-2">
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[12px] font-medium text-soft">{measure.label}</span>
      <span className="shrink-0 text-[14px] font-semibold text-ink tabular-nums">
        {show(measure.code, value)}
        {!FORMATS[measure.code]?.percent && (
          <span className="ml-1 text-[10px] font-normal text-faint">{measure.unit}</span>
        )}
      </span>
    </div>
    <div className="mt-1 flex flex-wrap items-center gap-1.5">
      {delta !== undefined && (
        <Pill tone={delta > 0 ? 'warn' : 'teal'} size="xs">
          {delta > 0 ? '+' : ''}
          {(delta * 100).toFixed(0)}% vs rest
        </Pill>
      )}
      {reference === 'WITHIN_WINDOW' && (
        <Pill size="xs">against this clip's widest moment</Pill>
      )}
      {reference === 'CALIBRATION' && (
        <Pill tone="ok" size="xs">against this patient at rest</Pill>
      )}
      {support !== undefined && <span className="text-[10px] text-faint">from {support}</span>}
    </div>
    <p className="mt-1 text-[11px] leading-relaxed text-faint">{measure.note}</p>
  </div>
);

const MeasureGroup: React.FC<{
  title: string;
  icon: React.ReactNode;
  order: readonly string[];
  observation: BehaviourObservation;
  byCode: Map<string, BehaviourMeasure>;
}> = ({ title, icon, order, observation, byCode }) => {
  const present = order.filter((code) => observation.measures[code] !== undefined);
  if (present.length === 0) return null;
  return (
    <Card className="space-y-3 p-4">
      <CardHead
        title={
          <span className="flex items-center gap-2">
            {icon}
            {title}
          </span>
        }
      />
      <div className="grid gap-2 sm:grid-cols-2">
        {present.map((code) => {
          const measure = byCode.get(code);
          if (!measure) return null;
          return (
            <Measure
              key={code}
              measure={measure}
              value={observation.measures[code]}
              delta={observation.deltas[code]}
              reference={observation.reference[code]}
              support={observation.support[code]}
            />
          );
        })}
      </div>
    </Card>
  );
};
