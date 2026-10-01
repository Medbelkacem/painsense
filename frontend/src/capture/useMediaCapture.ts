import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Camera and microphone capture.
 *
 * Four things this handles that a bare `getUserMedia` call does not:
 *
 * **It checks the secure context first.** Browsers refuse camera and microphone access outside
 * HTTPS or localhost, and they refuse it by throwing rather than by prompting — so a phone on
 * `http://192.168.x.x:5173` fails with no permission dialog and no obvious cause. Checking
 * `isSecureContext` up front turns that into a sentence the user can act on.
 *
 * **It maps the error names to something readable.** `NotAllowedError` and `NotReadableError`
 * mean completely different things to the person holding the phone — one is a permission they
 * denied, the other is another application already holding the camera — and "could not start
 * video source" helps nobody.
 *
 * **It stops every track.** The camera indicator light stays on until the last track is
 * stopped, and a user who pressed stop and still sees the light will reasonably conclude they
 * are being recorded. Stopping is therefore explicit, idempotent, and runs on unmount.
 *
 * **It re-enumerates after permission.** Device labels are empty strings before permission is
 * granted — a deliberate privacy measure — so the list is only worth showing afterwards.
 */

export type CaptureKind = 'camera' | 'microphone' | 'both';

export type CaptureStatus =
  | 'idle'
  | 'requesting'
  | 'live'
  | 'denied'
  | 'unsupported'
  | 'insecure'
  | 'error';

export interface CaptureDevice {
  deviceId: string;
  label: string;
  kind: MediaDeviceKind;
}

export interface CaptureState {
  status: CaptureStatus;
  stream: MediaStream | null;
  error: string | null;
  /** What the browser actually gave us, which is often not what was asked for. */
  settings: { width?: number; height?: number; frameRate?: number; sampleRate?: number } | null;
  cameras: CaptureDevice[];
  microphones: CaptureDevice[];
  facing: 'user' | 'environment';
}

const ERRORS: Record<string, string> = {
  NotAllowedError:
    'Permission was refused. Nothing is captured. To change it, use the camera or microphone ' +
    'icon in the address bar, or the site settings for this page.',
  PermissionDeniedError: 'Permission was refused. Nothing is captured.',
  NotFoundError:
    'No camera or microphone was found. On a laptop, check it is not disabled in the system ' +
    'settings or covered by a privacy shutter.',
  DevicesNotFoundError: 'No camera or microphone was found.',
  NotReadableError:
    'The device was found but could not be read. Another application is usually holding it — ' +
    'close any video call, camera app or other browser tab using it.',
  TrackStartError: 'The device could not be started. Another application is usually holding it.',
  OverconstrainedError:
    'No device matches what was asked for. Try the other camera, or clear the selection.',
  SecurityError:
    'The browser blocked access for security reasons. Camera and microphone need HTTPS, or ' +
    'localhost.',
  AbortError: 'The request was interrupted before the device started.',
};

function describe(cause: unknown): string {
  if (cause instanceof DOMException) {
    return ERRORS[cause.name] ?? `${cause.name}: ${cause.message}`;
  }
  return cause instanceof Error ? cause.message : 'The device could not be opened.';
}

export function useMediaCapture() {
  const [state, setState] = useState<CaptureState>({
    status: 'idle',
    stream: null,
    error: null,
    settings: null,
    cameras: [],
    microphones: [],
    facing: 'user',
  });

  // The stream is held in a ref as well as in state, so `stop` can reach the current one
  // without being re-created on every render and without a stale closure leaving a track open.
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      // Every track, not just the first. A video track stopped while its audio track runs
      // leaves the microphone live and, on most platforms, the indicator light on.
      stream.getTracks().forEach((track) => track.stop());
    }
    streamRef.current = null;
    setState((current) => ({
      ...current,
      status: 'idle',
      stream: null,
      settings: null,
      error: null,
    }));
  }, []);

  // Release the hardware if the component goes away while live — a route change should not
  // leave the camera running.
  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const enumerate = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const pick = (kind: MediaDeviceKind) =>
        devices
          .filter((device) => device.kind === kind)
          .map((device, index) => ({
            deviceId: device.deviceId,
            // Labels are empty until permission is granted, so a usable fallback matters.
            label: device.label || `${kind === 'videoinput' ? 'Camera' : 'Microphone'} ${index + 1}`,
            kind: device.kind,
          }));
      setState((current) => ({
        ...current,
        cameras: pick('videoinput'),
        microphones: pick('audioinput'),
      }));
    } catch {
      // Enumeration failing is not worth surfacing: the capture itself will report the real
      // problem, and a device list is a convenience.
    }
  }, []);

  useEffect(() => {
    enumerate();
    const media = navigator.mediaDevices;
    if (!media?.addEventListener) return;
    // A camera unplugged mid-session should disappear from the list.
    media.addEventListener('devicechange', enumerate);
    return () => media.removeEventListener('devicechange', enumerate);
  }, [enumerate]);

  const start = useCallback(
    async (
      kind: CaptureKind,
      options: {
        cameraId?: string;
        microphoneId?: string;
        facing?: 'user' | 'environment';
      } = {},
    ) => {
      if (!window.isSecureContext) {
        setState((current) => ({
          ...current,
          status: 'insecure',
          error:
            `This page is on ${window.location.protocol}//${window.location.host}, which the ` +
            'browser does not treat as a secure context. Camera and microphone are refused ' +
            'outside HTTPS and localhost — no permission prompt will appear. Run ' +
            './scripts/dev-cert.sh and reopen the page over https.',
        }));
        return null;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        setState((current) => ({
          ...current,
          status: 'unsupported',
          error: 'This browser does not expose getUserMedia. Camera and microphone are unavailable.',
        }));
        return null;
      }

      stop();
      setState((current) => ({ ...current, status: 'requesting', error: null }));

      const facing = options.facing ?? 'user';
      const wantVideo = kind === 'camera' || kind === 'both';
      const wantAudio = kind === 'microphone' || kind === 'both';

      const constraints: MediaStreamConstraints = {
        video: wantVideo
          ? options.cameraId
            ? { deviceId: { exact: options.cameraId } }
            : {
                // `ideal`, not `exact`: a laptop has no environment-facing camera and an
                // exact constraint would fail outright rather than giving the one it has.
                facingMode: { ideal: facing },
                width: { ideal: 640 },
                height: { ideal: 480 },
                frameRate: { ideal: 30 },
              }
          : false,
        audio: wantAudio
          ? options.microphoneId
            ? { deviceId: { exact: options.microphoneId } }
            : {
                // Off by default. These are designed to make speech intelligible on a call,
                // and they alter exactly the acoustic properties an analysis would measure.
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
              }
          : false,
      };

      try {
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        streamRef.current = stream;

        const video = stream.getVideoTracks()[0]?.getSettings() ?? {};
        const audio = stream.getAudioTracks()[0]?.getSettings() ?? {};
        setState((current) => ({
          ...current,
          status: 'live',
          stream,
          error: null,
          facing,
          settings: {
            width: video.width,
            height: video.height,
            frameRate: video.frameRate,
            sampleRate: audio.sampleRate,
          },
        }));
        // Labels are only populated once permission has been granted.
        enumerate();
        return stream;
      } catch (cause) {
        const denied =
          cause instanceof DOMException &&
          (cause.name === 'NotAllowedError' || cause.name === 'PermissionDeniedError');
        setState((current) => ({
          ...current,
          status: denied ? 'denied' : 'error',
          stream: null,
          error: describe(cause),
        }));
        return null;
      }
    },
    [enumerate, stop],
  );

  return { ...state, start, stop, refreshDevices: enumerate };
}
