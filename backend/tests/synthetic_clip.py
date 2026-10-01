"""Clips with a known answer, for testing the measurement.

A schematic face and a synthetic voice, rendered with the behaviour written into them: an
aperture, a pupil size, a brow position, a blink rate, a pitch, a jitter. The measurement
pipeline is then run over the result and asked to recover the numbers that went in.

**What this validates and what it does not.** It validates the arithmetic — that an iris
twice as wide gives half the millimetres per pixel, that a lid gap of a third of the iris
reads as an aperture of a third, that a pitch period perturbed by two percent reads as two
percent of jitter. It does not validate that a real face is detected, framed and segmented
as this one is, because a drawn face is not a photograph of a person. The cascade's own
detection rate is published upstream and is not this suite's to re-measure; what is this
suite's business is that nothing downstream of it is wrong.

The face is drawn photometrically rather than prettily. A Viola-Jones cascade keys on a
dark band across the eyes above a bright nose bridge and brighter cheeks, so those are what
is laid down, in that order of brightness. It is enough for the detector to fire, which is
all that is wanted here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

SAMPLE_RATE = 22050
FRAME_RATE = 25
WIDTH, HEIGHT = 640, 480

#: Iris radius in the drawn face, in pixels. The measurement should recover this, and every
#: millimetre figure is scaled by it.
IRIS_RADIUS_PX = 15


def face(
    *,
    aperture: float = 1.0,
    pupil: float = 0.34,
    brow_drop: float = 0.0,
    mouth: float = 0.0,
    shift: tuple[int, int] = (0, 0),
    brightness: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """One grayscale frame.

    `aperture` is the lid gap as a fraction of the iris diameter, so 1.0 leaves the iris
    fully visible and 0.0 closes the lids over it. `pupil` is the pupil radius as a
    fraction of the iris radius. `brow_drop` lowers the eyebrow towards the eye.
    """
    rng = np.random.default_rng(seed)
    image = np.full((HEIGHT, WIDTH), 90, np.uint8)
    centre_x, centre_y = WIDTH // 2 + shift[0], HEIGHT // 2 + shift[1]
    face_width, face_height = 230, 300

    cv2.ellipse(
        image, (centre_x, centre_y), (face_width // 2, face_height // 2), 0, 0, 360, 185, -1
    )
    # Forehead, nose bridge and cheeks: the bright regions the cascade reads the dark eye
    # band against.
    cv2.ellipse(
        image,
        (centre_x, centre_y - face_height // 5),
        (face_width // 2 - 8, face_height // 4),
        0, 0, 360, 205, -1,
    )
    cv2.ellipse(image, (centre_x, centre_y + 10), (16, 60), 0, 0, 360, 215, -1)

    gap = round(2 * IRIS_RADIUS_PX * aperture)
    for side in (-1, 1):
        eye_x, eye_y = centre_x + side * 52, centre_y - 36
        cv2.ellipse(image, (eye_x, eye_y), (46, 30), 0, 0, 360, 150, -1)
        cv2.ellipse(image, (eye_x, eye_y), (34, 20), 0, 0, 360, 232, -1)
        cv2.circle(image, (eye_x, eye_y), IRIS_RADIUS_PX, 58, -1)
        if pupil > 0:
            cv2.circle(
                image, (eye_x, eye_y), max(2, round(IRIS_RADIUS_PX * pupil)), 16, -1
            )
        # The lids, laid over the iris from above and below, meeting when the gap is zero.
        lid = 205
        image[max(eye_y - IRIS_RADIUS_PX - 14, 0) : eye_y - gap // 2, eye_x - 48 : eye_x + 48] = lid
        image[eye_y + (gap + 1) // 2 : eye_y + IRIS_RADIUS_PX + 14, eye_x - 48 : eye_x + 48] = lid
        cv2.ellipse(
            image, (eye_x, eye_y - 34 + int(brow_drop * 16)), (36, 7), 0, 0, 360, 70, -1
        )
        cv2.ellipse(
            image, (centre_x + side * 78, centre_y + 6), (26, 40), 0, 0, 360, 198, -1
        )

    cv2.ellipse(
        image,
        (centre_x, centre_y + 86),
        (46, max(2, int(4 + mouth * 26))),
        0, 0, 360, 95, -1,
    )
    image = cv2.GaussianBlur(image, (5, 5), 0)
    blended = image.astype(float) * brightness + rng.normal(0, 3, image.shape)
    return np.clip(blended, 0, 255).astype(np.uint8)


def voice(
    *,
    pitch: float = 140.0,
    seconds: float = 12.0,
    jitter: float = 0.0,
    shimmer: float = 0.0,
    noise: float = 0.0,
    seed: int = 1,
) -> np.ndarray:
    """A pulse train at `pitch`, with the period and amplitude perturbation asked for.

    Shaped by a decaying exponential so it has the harmonic structure of a voiced sound
    rather than the single partial of a sine. `jitter` and `shimmer` are the standard
    deviations of the relative perturbation, not the measures themselves: the mean absolute
    difference between consecutive draws of a normal variable is 2/sqrt(pi) times its
    standard deviation, so a jitter of 0.02 here should be measured as about 2.26%.
    """
    rng = np.random.default_rng(seed)
    samples = np.zeros(int(SAMPLE_RATE * seconds))
    decay = np.exp(-np.arange(int(SAMPLE_RATE * 0.008)) / (SAMPLE_RATE * 0.0015))
    moment = 0.0
    while moment < seconds - 0.01:
        period = (1.0 / pitch) * (1.0 + rng.normal(0, jitter))
        amplitude = 1.0 + rng.normal(0, shimmer)
        start = int(moment * SAMPLE_RATE)
        stop = min(start + len(decay), len(samples))
        samples[start:stop] += amplitude * decay[: stop - start]
        moment += max(period, 1e-4)
    if noise:
        samples += rng.normal(0, noise, len(samples))
    return samples / max(np.max(np.abs(samples)), 1e-9) * 0.6


def clip(
    destination: Path,
    *,
    aperture: float = 1.0,
    pupil: float = 0.34,
    brow_drop: float = 0.0,
    blinks_per_min: float = 15.0,
    pitch: float = 140.0,
    jitter: float = 0.004,
    shimmer: float = 0.0,
    noise: float = 0.0,
    seconds: float = 12.0,
    silent: bool = False,
) -> Path:
    """Write a WebM clip with the given behaviour in it.

    Blinks are three frames long, which at 25 fps is 120 ms — a real blink. The lids meet
    completely during one, because a blink that leaves a slit of iris open is not a blink
    and the closure detection would be right to ignore it.
    """
    frames = int(FRAME_RATE * seconds)
    interval = int(FRAME_RATE * 60 / blinks_per_min) if blinks_per_min else frames + 1
    raw = destination.with_suffix(".gray")
    with raw.open("wb") as handle:
        for index in range(frames):
            blinking = index % interval < 3
            handle.write(
                face(
                    aperture=0.0 if blinking else aperture,
                    pupil=pupil,
                    brow_drop=brow_drop,
                    seed=index,
                ).tobytes()
            )

    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FRAME_RATE), "-i", str(raw),
    ]
    wav = destination.with_suffix(".wav")
    if not silent:
        from scipy.io import wavfile

        signal = voice(
            pitch=pitch, seconds=seconds, jitter=jitter, shimmer=shimmer, noise=noise
        )
        wavfile.write(wav, SAMPLE_RATE, (signal * 32767).astype(np.int16))
        command += ["-i", str(wav), "-c:a", "libopus"]
    command += ["-c:v", "libvpx-vp9", "-b:v", "600k", "-pix_fmt", "yuv420p"]
    command.append(str(destination))

    subprocess.run(command, check=True, capture_output=True)
    raw.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    return destination


def audio_only(destination: Path, **kwargs) -> Path:
    """A clip with a voice and no picture, which is what a microphone-only capture gives."""
    from scipy.io import wavfile

    signal = voice(**kwargs)
    wav = destination.with_suffix(".wav")
    wavfile.write(wav, SAMPLE_RATE, (signal * 32767).astype(np.int16))
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
            "-c:a", "libopus", str(destination),
        ],
        check=True,
        capture_output=True,
    )
    wav.unlink(missing_ok=True)
    return destination
