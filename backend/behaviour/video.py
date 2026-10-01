"""Reading a clip frame by frame.

The job here is to find the face, hand the eyes to `eyes.measure`, and take the few other
things a face box makes measurable: where the brow sits, whether the mouth is open, how
much the head is moving, and whether the picture is good enough to believe.

**Where the eyes are is calibrated, not assumed.** This is the part that took two attempts
to get right, so it is worth writing down. There is a cascade for eyes in the library, and
using it frame by frame does not work: it is trained on open eyes, so it stops firing the
moment the patient blinks, which throws away every frame of the one behaviour most worth
counting and leaves a shut eye and an absent face looking identical. Falling back to fixed
proportions of the face box does not work either, because the dark round thing nearest the
middle of a generous eye window is sometimes the eyebrow — and a clip of a sleeping patient
then comes back with two open eyes and a plausible pupil, measured off their eyebrows.

So the two are combined. A first pass runs the eye cascade over a sample of frames and
records where it found eyes **relative to the face box**, which gives a window fitted to
this patient's face rather than to an average one. The measuring pass then uses that window
on every frame, including the frames where the eyes are shut — the cascade says where to
look while the eyes are open, and the calibration keeps looking there once they close. A
clip where the cascade never fires falls back to the published proportions and is noted,
and the eyes-open gate refuses it anyway.

**Detection runs on a downscaled copy.** A face is hundreds of pixels across and the
cascade finds it just as well at half size, at a quarter of the cost. The measurements are
then taken from the full-resolution frame, where the iris is still tens of pixels wide.

**Frames are sampled, not all read.** Blink timing needs about ten frames a second and
nothing here needs more, so a 30 fps clip is read at every third frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from backend.behaviour import schema
from backend.behaviour.eyes import CLOSED, EyeReading, measure

NAN = float("nan")


@dataclass(frozen=True)
class Window:
    """A region of interest as fractions of the face box: left, right, top, bottom."""

    x0: float
    x1: float
    y0: float
    y1: float

    def shifted_up(self, by: float) -> Window:
        height = self.y1 - self.y0
        return Window(
            self.x0, self.x1, max(0.0, self.y0 - by * height), max(0.0, self.y1 - by * height)
        )


#: Where the iris width comes from, best first.
FROM_CASCADE = "CASCADE"
FROM_ANATOMY = "ANATOMY"

#: Iris half-width as a share of the face box width, for a patient whose own iris was
#: never seen. It is an anatomical constant run through two steps: the visible iris is
#: 11.7 mm across, an adult face is about 139 mm across the cheekbones, and the box this
#: cascade returns is somewhat wider than the face itself. The band around it is wide
#: because that last factor is the loose one — but it does not need to be tight. The job
#: is only to tell an iris from an eyebrow, and a brow is two to three times as wide.
IRIS_RADIUS_FACE_FRACTION = 0.035
ANATOMICAL_TOLERANCE = 0.6


@dataclass(frozen=True)
class Calibration:
    """What the first pass learned about this patient's eyes.

    The windows say where to look. The iris width is what lets a later frame tell a closed
    eye from an eyebrow, and it is held as a share of the face box width so that it scales
    by itself when the patient leans towards the camera.

    The width is measured on this patient wherever the eye cascade found their eyes open.
    Where it did not — and a patient who squints through the whole recording is the case
    that matters, because squinting is what the cascade refuses to fire on and also what
    there is to measure — the anatomical share is used instead, with a wider band around
    it, and the source is recorded so a reader knows which they have.
    """

    left: Window
    right: Window
    iris_fraction: float = IRIS_RADIUS_FACE_FRACTION
    source: str = FROM_ANATOMY

    @property
    def tolerance(self) -> float:
        from backend.behaviour.eyes import IRIS_WIDTH_TOLERANCE

        return ANATOMICAL_TOLERANCE if self.source == FROM_ANATOMY else IRIS_WIDTH_TOLERANCE

    def iris_radius_px(self, face_width: int) -> float:
        return self.iris_fraction * face_width


#: Where the parts of a face sit inside the box this cascade returns, as fractions of its
#: width and height. The box runs roughly from the forehead to the chin. These are the
#: fallback only: the eye windows are normally calibrated per face, and these are what a
#: clip whose eyes the cascade never saw falls back to.
DEFAULT_LEFT_EYE = Window(0.12, 0.46, 0.30, 0.56)
DEFAULT_RIGHT_EYE = Window(0.54, 0.88, 0.30, 0.56)
MOUTH = Window(0.26, 0.74, 0.60, 0.94)

#: How far above the eye window the brow band sits, as a multiple of that window's height.
BROW_OFFSET = 0.95

#: Longest side the frame is scaled to before a cascade runs.
DETECTION_WIDTH = 320

#: Smallest face, as a fraction of the detection image's height. A face smaller than this
#: has an iris a couple of pixels across, and nothing useful comes out of it.
MINIMUM_FACE_SHARE = 0.18

#: Cascade parameters. 1.1 and 5 are the long-standing defaults for this cascade and are
#: kept because they are what its published false-positive rate refers to.
SCALE_FACTOR = 1.1
MINIMUM_NEIGHBOURS = 5

#: Target frames per second for the analysis.
ANALYSIS_FRAME_RATE = 10.0

#: Frames the calibration pass looks at, spread evenly through the clip, and how many of
#: them have to yield a pair of eyes before the calibration is trusted. Spread rather than
#: taken from the start, because a patient settles into the frame.
CALIBRATION_FRAMES = 24
CALIBRATION_MINIMUM = 3

#: How much of the face box's width and height the calibrated eye window is padded by
#: around the cascade's own box. The cascade frames an eye tightly; a little margin keeps
#: the iris inside when the head tilts, without reaching up to the brow.
EYE_PADDING = 0.03

#: A frame whose face region has a Laplacian variance below this is out of focus or
#: motion-blurred, and an iris edge measured in it is a guess.
SHARPNESS_FLOOR = 25.0

#: A face region outside this mean brightness is under- or over-exposed. The thresholds are
#: wide: the equalisation inside the eye measurement recovers a great deal, and refusing a
#: dim clip outright would refuse most ward lighting.
BRIGHTNESS_RANGE = (35.0, 225.0)

_FACE_FILE = "haarcascade_frontalface_default.xml"
#: The eyeglasses-tolerant eye cascade, because a patient in spectacles is ordinary.
_EYE_FILE = "haarcascade_eye_tree_eyeglasses.xml"

#: Where to look for a cascade. The wheel ships them, which is the normal case; the second
#: is where the Debian and Ubuntu `opencv-data` package puts them, for a deployment running
#: against a system OpenCV.
_CASCADE_DIRECTORIES = (
    Path(cv2.data.haarcascades),
    Path("/usr/share/opencv4/haarcascades"),
)


class VideoUnreadable(RuntimeError):
    """The clip could not be decoded, or holds no frame."""


@dataclass(frozen=True)
class FrameReading:
    index: int
    time_s: float
    #: None where no front-facing view was found. Distinct from a face found with the eyes
    #: shut, which is a face box with two closed eye readings.
    face: tuple[int, int, int, int] | None
    left: EyeReading = CLOSED
    right: EyeReading = CLOSED
    #: Distance from the brow to the eye, over face height. Falls as the brow lowers.
    brow_gap_ratio: float = NAN
    #: Vertical opening of the mouth over face width.
    mouth_open_ratio: float = NAN
    #: Laplacian variance over the face region.
    sharpness: float = NAN
    #: Mean brightness of the face region.
    brightness: float = NAN

    @property
    def eyes_open(self) -> bool:
        return self.left.measurable and self.right.measurable


@dataclass
class VideoReading:
    frame_rate: float
    duration_seconds: float
    width: int
    height: int
    #: Frames the file holds, against frames actually analysed after sampling.
    frames_decoded: int = 0
    frames: list[FrameReading] = field(default_factory=list)
    #: True where the eye windows were fitted to this face rather than assumed.
    eyes_calibrated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def analysed(self) -> int:
        return len(self.frames)

    @property
    def with_face(self) -> list[FrameReading]:
        return [frame for frame in self.frames if frame.face is not None]

    @property
    def with_eyes_open(self) -> list[FrameReading]:
        return [frame for frame in self.frames if frame.eyes_open]


def _cascade(filename: str) -> cv2.CascadeClassifier:
    for directory in _CASCADE_DIRECTORIES:
        path = directory / filename
        if path.exists():
            classifier = cv2.CascadeClassifier(str(path))
            if not classifier.empty():
                return classifier
    raise VideoUnreadable(
        f"the cascade {filename} was not found in "
        + " or ".join(str(directory) for directory in _CASCADE_DIRECTORIES)
        + ". These ship with the opencv-python wheel; a deployment against a system OpenCV "
        "needs the opencv-data package."
    )


def _downscale(gray: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = gray.shape
    scale = min(1.0, DETECTION_WIDTH / width) if width else 1.0
    if scale >= 1.0:
        return gray, 1.0
    small = cv2.resize(
        gray, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
    )
    return small, scale


def _largest_face(
    gray: np.ndarray, classifier: cv2.CascadeClassifier
) -> tuple[int, int, int, int] | None:
    """The biggest front-facing view in the frame, in full-resolution coordinates.

    The biggest rather than the first: a clinician's own face at the edge of the frame is a
    real possibility, and the patient is the one filling it.
    """
    small, scale = _downscale(gray)
    minimum = int(small.shape[0] * MINIMUM_FACE_SHARE)
    faces = classifier.detectMultiScale(
        small,
        scaleFactor=SCALE_FACTOR,
        minNeighbors=MINIMUM_NEIGHBOURS,
        minSize=(minimum, minimum),
    )
    if len(faces) == 0:
        return None
    x, y, box_width, box_height = max(faces, key=lambda box: int(box[2]) * int(box[3]))
    back = 1.0 / scale
    return (int(x * back), int(y * back), int(box_width * back), int(box_height * back))


def _eye_windows(
    gray: np.ndarray, face: tuple[int, int, int, int], classifier: cv2.CascadeClassifier
) -> tuple[Window, Window] | None:
    """The two eye windows this frame supports, as fractions of the face box.

    Returns None unless exactly one eye is found on each side of the face's midline. Two
    candidates on one side means one of them is a brow or a nostril, and a guess between
    them would be the thing this calibration exists to avoid.
    """
    x, y, face_width, face_height = face
    upper = gray[y : y + int(face_height * 0.6), x : x + face_width]
    if upper.size == 0:
        return None
    small, scale = _downscale(upper)
    found = classifier.detectMultiScale(
        small, scaleFactor=SCALE_FACTOR, minNeighbors=MINIMUM_NEIGHBOURS
    )
    if len(found) < 2:
        return None

    back = 1.0 / scale
    boxes = [
        (box[0] * back, box[1] * back, box[2] * back, box[3] * back) for box in found
    ]
    middle = face_width / 2
    left = [box for box in boxes if box[0] + box[2] / 2 < middle]
    right = [box for box in boxes if box[0] + box[2] / 2 >= middle]
    if len(left) != 1 or len(right) != 1:
        return None

    def to_window(box) -> Window:
        box_x, box_y, box_w, box_h = box
        return Window(
            max(0.0, box_x / face_width - EYE_PADDING),
            min(1.0, (box_x + box_w) / face_width + EYE_PADDING),
            max(0.0, box_y / face_height - EYE_PADDING),
            min(1.0, (box_y + box_h) / face_height + EYE_PADDING),
        )

    return to_window(left[0]), to_window(right[0])


def _calibrate(
    path: Path, step: int, faces: cv2.CascadeClassifier, eyes: cv2.CascadeClassifier
) -> Calibration | None:
    """Where this patient's eyes sit in their face box, and how wide their iris is.

    Medians over the frames that agreed, so one bad detection cannot move the window or
    the width. The iris width is measured inside the windows this pass has just found,
    which is the only point in the clip where the eyes are known to be open — the cascade
    only fires on an open eye, which is the whole reason this pass exists.
    """
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sampled = max(step, total // CALIBRATION_FRAMES if total else step)

    collected: list[tuple[Window, Window]] = []
    widths: list[float] = []
    index = 0
    while len(collected) < CALIBRATION_FRAMES:
        ok, frame = capture.read()
        if not ok:
            break
        if index % sampled == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face = _largest_face(gray, faces)
            if face is not None:
                pair = _eye_windows(gray, face, eyes)
                if pair is not None:
                    collected.append(pair)
                    for window in pair:
                        reading = measure(_crop(gray, face, window))
                        if reading.measurable:
                            widths.append(reading.iris_radius_px / face[2])
        index += 1
    capture.release()

    if len(collected) < CALIBRATION_MINIMUM:
        return None
    left, right = (
        Window(
            *(
                float(np.median([getattr(pair[side], name) for pair in collected]))
                for name in ("x0", "x1", "y0", "y1")
            )
        )
        for side in (0, 1)
    )
    if not widths:
        return Calibration(left=left, right=right)
    return Calibration(
        left=left,
        right=right,
        iris_fraction=float(np.median(widths)),
        source=FROM_CASCADE,
    )


def _crop(gray: np.ndarray, face: tuple[int, int, int, int], window: Window) -> np.ndarray:
    x, y, width, height = face
    left = max(int(x + width * window.x0), 0)
    right = min(int(x + width * window.x1), gray.shape[1])
    top = max(int(y + height * window.y0), 0)
    bottom = min(int(y + height * window.y1), gray.shape[0])
    if bottom <= top or right <= left:
        return np.empty((0, 0), dtype=gray.dtype)
    return gray[top:bottom, left:right]


def _dark_centroid_row(window: np.ndarray) -> float:
    """Row of the centre of the darkest structure in the window, as a fraction of it.

    Used for the eyebrow, which in a band above the eye is the one dark horizontal thing
    there is. Returns NaN when the band has no dark structure to speak of — a very fair
    brow, or a band that landed on a fringe of hair covering all of it.
    """
    if window.size == 0:
        return NAN
    smoothed = cv2.GaussianBlur(window, (5, 5), 0)
    cut, _ = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = smoothed <= cut
    share = float(mask.mean())
    # Nothing dark, or everything dark: either way there is no structure to locate.
    if share < 0.04 or share > 0.75:
        return NAN
    weights = mask.sum(axis=1).astype(float)
    return float((np.arange(len(weights)) * weights).sum() / weights.sum()) / window.shape[0]


def _mouth_opening(window: np.ndarray) -> float:
    """Vertical extent of the mouth opening, in pixels.

    An open mouth is a dark gap between the lips, and closed lips are a dark line. The
    measure is therefore the height of the darkest connected structure, which is a line a
    few pixels tall when the mouth is shut and a wide oval when it is open.
    """
    if window.size == 0:
        return NAN
    smoothed = cv2.GaussianBlur(window, (5, 5), 0)
    cut, _ = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (smoothed <= cut).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return 0.0
    # The widest component, not the tallest: the mouth runs across the band, while a
    # shadow at its edge runs down it.
    widest = max(range(1, count), key=lambda index: int(stats[index][2]))
    return float(stats[widest][3])


def read(path: Path, *, frame_rate: float = ANALYSIS_FRAME_RATE) -> VideoReading:
    """Decode a clip and measure every sampled frame."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise VideoUnreadable(f"{path.name} could not be opened as a video")

    source_rate = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    face_cascade = _cascade(_FACE_FILE)
    eye_cascade = _cascade(_EYE_FILE)

    reading = VideoReading(
        frame_rate=source_rate, duration_seconds=0.0, width=width, height=height
    )
    assumed_rate = source_rate
    if assumed_rate <= 0:
        # A stream written by a browser often carries no frame rate in its header. Falling
        # back to the browser's own default is better than refusing the clip, and the
        # assumption is recorded rather than hidden.
        assumed_rate = 30.0
        reading.notes.append(
            "the file declares no frame rate; 30 fps was assumed for the timing of blinks"
        )
    step = max(1, round(assumed_rate / frame_rate))

    calibrated = _calibrate(path, step, face_cascade, eye_cascade) or Calibration(
        DEFAULT_LEFT_EYE, DEFAULT_RIGHT_EYE
    )
    reading.eyes_calibrated = calibrated.source == FROM_CASCADE
    left_window, right_window = calibrated.left, calibrated.right
    if not reading.eyes_calibrated:
        reading.notes.append(
            "the eye cascade found no open pair of eyes to fit the windows and the iris "
            "width to, so the average proportions of a face and the anatomical iris width "
            "were used instead. A patient who squinted or kept their eyes shut throughout "
            "is the usual reason, and squinting is exactly what that cascade declines to "
            "fire on. The eye measures are still taken, against a wider tolerance"
        )
    brow_windows = (left_window.shifted_up(BROW_OFFSET), right_window.shifted_up(BROW_OFFSET))

    decoded = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index = decoded
        decoded += 1
        if index % step:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        moment = index / assumed_rate
        face = _largest_face(gray, face_cascade)
        if face is None:
            reading.frames.append(FrameReading(index=index, time_s=moment, face=None))
            continue

        x, y, face_width, face_height = face
        region = gray[max(y, 0) : y + face_height, max(x, 0) : x + face_width]
        expected = calibrated.iris_radius_px(face_width)
        tolerance = calibrated.tolerance

        # Brow position is read against the eye window it sits above, so a nodding head
        # does not read as a brow movement.
        brow_rows = [_dark_centroid_row(_crop(gray, face, band)) for band in brow_windows]
        usable = [value for value in brow_rows if not np.isnan(value)]
        brow_gap = NAN
        if usable:
            band = brow_windows[0]
            brow_centre = band.y0 + float(np.mean(usable)) * (band.y1 - band.y0)
            eye_centre = (left_window.y0 + left_window.y1) / 2
            brow_gap = eye_centre - brow_centre

        mouth = _mouth_opening(_crop(gray, face, MOUTH))
        reading.frames.append(
            FrameReading(
                index=index,
                time_s=moment,
                face=face,
                left=measure(_crop(gray, face, left_window), expected, tolerance),
                right=measure(_crop(gray, face, right_window), expected, tolerance),
                brow_gap_ratio=brow_gap,
                mouth_open_ratio=NAN if np.isnan(mouth) else mouth / face_width,
                sharpness=(
                    float(cv2.Laplacian(region, cv2.CV_64F).var()) if region.size else NAN
                ),
                brightness=float(region.mean()) if region.size else NAN,
            )
        )

    capture.release()
    reading.frames_decoded = decoded
    reading.duration_seconds = decoded / assumed_rate if assumed_rate else 0.0
    if not reading.frames:
        raise VideoUnreadable(f"{path.name} holds no decodable frame")
    if assumed_rate < schema.MINIMUM_FRAME_RATE:
        reading.notes.append(
            f"the clip runs at {assumed_rate:.1f} fps, below the "
            f"{schema.MINIMUM_FRAME_RATE:g} fps a blink lasting a tenth of a second needs "
            "to be seen at all"
        )
    return reading
