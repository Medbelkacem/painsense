import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Recording a fixed-length clip from a live stream.
 *
 * `useMediaCapture` opens the devices; this records from them. The two are separate because
 * the camera has to be live and framed before anyone presses record — the operator needs to
 * see that the patient is in shot and looking at the lens, and that is not something to
 * discover from a failed measurement afterwards.
 *
 * Four things this handles.
 *
 * **It picks a container the browser will actually produce.** `MediaRecorder` silently
 * ignores a mime type it cannot encode on some browsers and throws on others, so the
 * candidates are tested with `isTypeSupported` and the first that passes is used. WebM with
 * VP9 and Opus is the common case; Safari produces MP4.
 *
 * **It stops itself.** The clip is a fixed length because the measurement needs a known
 * window and because a recording that runs until somebody remembers to stop it is a
 * recording of a patient sitting in a chair. The countdown is exposed so the interface can
 * show the patient how long is left.
 *
 * **It asks for data in slices.** Without a timeslice some browsers deliver one blob at
 * stop and others deliver nothing if the track ends first; a one-second slice means the
 * chunks accumulate as they go and an interrupted recording still holds what it captured.
 *
 * **It never holds the clip longer than the page.** The blob lives in state until it is
 * uploaded or discarded, and the object URL made for the review player is revoked when it
 * is replaced.
 */

export type RecorderStatus = 'idle' | 'recording' | 'ready' | 'unsupported' | 'error';

/** In order of preference. The first the browser admits to supporting is used. */
const CANDIDATE_TYPES = [
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
  'video/mp4',
];

const AUDIO_ONLY_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

/** How often the recorder is asked to hand over what it has. */
const SLICE_MS = 1000;

export interface Clip {
  blob: Blob;
  /** The media type to send, with any codec parameters stripped off. */
  mediaType: string;
  seconds: number;
  url: string;
}

export interface ClipRecorder {
  status: RecorderStatus;
  error: string | null;
  /** Whole seconds left in the current recording. */
  remaining: number;
  clip: Clip | null;
  start: (seconds: number) => void;
  stop: () => void;
  discard: () => void;
}

function supportedType(hasVideo: boolean): string | null {
  if (typeof MediaRecorder === 'undefined') return null;
  const candidates = hasVideo ? CANDIDATE_TYPES : AUDIO_ONLY_TYPES;
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

export function useClipRecorder(stream: MediaStream | null): ClipRecorder {
  const [status, setStatus] = useState<RecorderStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [clip, setClip] = useState<Clip | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number | null>(null);
  const startedAt = useRef<number>(0);
  // The object URL of the clip currently in state, so it can be revoked on replacement.
  const objectUrl = useRef<string | null>(null);

  const release = useCallback(() => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }, []);

  useEffect(() => release, [release]);

  // A stream that goes away mid-recording ends the recording rather than leaving the
  // interface counting down against a camera that is no longer open.
  useEffect(() => {
    if (stream === null && recorder.current) {
      recorder.current.stop();
      recorder.current = null;
      if (timer.current !== null) window.clearInterval(timer.current);
      setStatus('idle');
      setRemaining(0);
    }
  }, [stream]);

  const stop = useCallback(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
    const active = recorder.current;
    if (active && active.state !== 'inactive') active.stop();
  }, []);

  const discard = useCallback(() => {
    release();
    setClip(null);
    setStatus(stream ? 'idle' : 'idle');
  }, [release, stream]);

  const start = useCallback(
    (seconds: number) => {
      if (!stream) {
        setStatus('error');
        setError('The camera and microphone are not open.');
        return;
      }
      const hasVideo = stream.getVideoTracks().length > 0;
      const mimeType = supportedType(hasVideo);
      if (!mimeType) {
        setStatus('unsupported');
        setError(
          'This browser cannot record from the camera. The measurement needs a recorded ' +
            'clip, so the capture cannot proceed here.',
        );
        return;
      }

      release();
      setClip(null);
      setError(null);
      chunks.current = [];

      let active: MediaRecorder;
      try {
        active = new MediaRecorder(stream, { mimeType });
      } catch (cause) {
        setStatus('error');
        setError(cause instanceof Error ? cause.message : 'The recorder could not be started.');
        return;
      }

      active.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.current.push(event.data);
      };
      active.onerror = () => {
        setStatus('error');
        setError('The recording failed part-way through. Nothing was kept.');
      };
      active.onstop = () => {
        const elapsed = (Date.now() - startedAt.current) / 1000;
        const blob = new Blob(chunks.current, { type: mimeType });
        chunks.current = [];
        recorder.current = null;
        if (blob.size === 0) {
          setStatus('error');
          setError('The recording came back empty. Nothing was captured.');
          return;
        }
        const url = URL.createObjectURL(blob);
        objectUrl.current = url;
        setClip({
          blob,
          // The server matches on the container, not on the codecs inside it.
          mediaType: mimeType.split(';')[0],
          seconds: Math.round(elapsed * 10) / 10,
          url,
        });
        setStatus('ready');
      };

      recorder.current = active;
      startedAt.current = Date.now();
      active.start(SLICE_MS);
      setStatus('recording');
      setRemaining(seconds);

      timer.current = window.setInterval(() => {
        const left = seconds - (Date.now() - startedAt.current) / 1000;
        if (left <= 0) {
          setRemaining(0);
          stop();
          return;
        }
        setRemaining(Math.ceil(left));
      }, 200);
    },
    [release, stop, stream],
  );

  return { status, error, remaining, clip, start, stop, discard };
}
