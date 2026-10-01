import { useEffect, useRef, useState } from 'react';

/**
 * A live waveform and level from a microphone stream, via the Web Audio API.
 *
 * The analyser is fed the time-domain signal rather than the FFT, because what the operator
 * needs to see is whether the microphone is picking anything up at all — a trace that moves
 * when they speak. Spectral features are a server-side job on the saved audio, not something
 * to derive from a display buffer.
 *
 * Two practical notes. An `AudioContext` created before a user gesture starts suspended under
 * every browser's autoplay policy, so it is resumed explicitly. And the context is closed on
 * teardown: leaving it open holds an audio device handle and, on some platforms, the
 * microphone indicator.
 */

const FFT_SIZE = 2048;
const WAVEFORM_POINTS = 256;

export interface AudioLevel {
  /** Downsampled time-domain samples in [-1, 1], for drawing. */
  waveform: number[];
  /** Root mean square of the current frame, in [0, 1]. */
  rms: number;
  /** Highest absolute sample in the current frame, for clipping. */
  peak: number;
  /** True while the frame is at or near full scale, where the input is too hot to analyse. */
  clipping: boolean;
  /** True while nothing above the noise floor is arriving. */
  silent: boolean;
}

const QUIET = 0.005;
const CLIP = 0.98;

export function useAudioLevel(stream: MediaStream | null): AudioLevel {
  const [level, setLevel] = useState<AudioLevel>({
    waveform: Array.from({ length: WAVEFORM_POINTS }, () => 0),
    rms: 0,
    peak: 0,
    clipping: false,
    silent: true,
  });
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const track = stream?.getAudioTracks()[0];
    if (!stream || !track) {
      setLevel({
        waveform: Array.from({ length: WAVEFORM_POINTS }, () => 0),
        rms: 0,
        peak: 0,
        clipping: false,
        silent: true,
      });
      return;
    }

    const AudioContextClass =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;

    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = FFT_SIZE;
    source.connect(analyser);
    // Deliberately not connected to the destination: routing the microphone to the speakers
    // is a feedback loop, and nobody wants to hear themselves.

    void context.resume();

    const buffer = new Float32Array(analyser.fftSize);
    const stride = Math.max(1, Math.floor(buffer.length / WAVEFORM_POINTS));

    const tick = () => {
      analyser.getFloatTimeDomainData(buffer);
      let sum = 0;
      let peak = 0;
      for (let index = 0; index < buffer.length; index += 1) {
        const value = buffer[index];
        sum += value * value;
        const magnitude = Math.abs(value);
        if (magnitude > peak) peak = magnitude;
      }
      const rms = Math.sqrt(sum / buffer.length);
      const waveform: number[] = [];
      for (let index = 0; index < buffer.length; index += stride) {
        waveform.push(buffer[index]);
      }
      setLevel({
        waveform,
        rms,
        peak,
        clipping: peak >= CLIP,
        silent: rms < QUIET,
      });
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);

    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      source.disconnect();
      analyser.disconnect();
      void context.close();
    };
  }, [stream]);

  return level;
}
