"""Measuring an eye.

The patient is asked to look at the camera with their eyes open, and this is what reads
them. Everything comes from one segmentation: the iris, which in a grayscale image of an
eye is the dark compact region in the middle of the opening.

Finding the iris gives three things at once.

**A ruler.** The horizontal visible iris diameter is close to 11.7 mm in every adult eye,
so the pixels-to-millimetres factor falls out of the segmentation itself. Nothing has to be
calibrated and the patient can sit wherever they like.

**The aperture.** In an open adult eye the lids cross the iris top and bottom, so the
visible iris is a disc with two chords cut off it. Its height over its width is a direct
reading of how far the lids have closed, and it is scale-free by construction. The measure
saturates in the rare case of a lid retracted clear of the iris — a startled stare — which
is reported as a ceiling rather than extrapolated past.

**The pupil.** Inside the iris, the pupil is darker again. Thresholding within the iris
alone, rather than across the image, is what makes this survive a room where one side of
the face is brighter than the other.

A closed eye has no iris to find. That is the signal, not a failure, which is why a reading
carries `found` and `open` separately: nothing found in a window where a face was located
means the eye was shut, while nothing found because there was no face at all is a different
thing and is decided a level up.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from backend.behaviour import schema

#: A candidate smaller or larger than this share of the eye window is not an iris. The
#: lower bound throws out lash fragments and specular noise, the upper bound throws out a
#: window that is mostly eyebrow or mostly shadow.
IRIS_AREA_SHARE = (0.008, 0.30)

#: How far a candidate's half-width may sit from the iris width measured for this patient
#: during calibration. This is what stops an eyebrow being measured as an iris, and it is
#: the only test that does the job when the eyes are shut. With the lids closed there is
#: no iris in the window and the brow is the one dark round-ish thing left, so it wins
#: every test that asks what a candidate looks like — it is a solid dark blob near the
#: middle of a window that has moved up with the closing lids. What it cannot do is be the
#: right size: a brow is two or three times as wide as the iris above which it sits. So the
#: calibration measures this patient's own iris while their eyes are open, and anything
#: that far off that width afterwards is not their iris.
IRIS_WIDTH_TOLERANCE = 0.45

#: Widest a candidate may be as a share of the eye window, used when no calibrated width
#: is available. An eye window frames the whole opening and the iris covers about half its
#: width, so a blob spanning most of it is a brow or a shadow.
IRIS_WINDOW_SHARE_LIMIT = 0.6

#: How far from round a candidate may be, and the two limits differ on purpose. A visible
#: iris is legitimately wide and flat whenever the lids are close together — that is the
#: whole point of the aperture measure — so squeezing the horizontal limit would make a
#: squeezed eye indistinguishable from no eye at all. Nothing in an eye window is
#: legitimately tall and narrow, so that limit stays tight and keeps out hair.
IRIS_WIDE_LIMIT = 8.0
IRIS_TALL_LIMIT = 2.5

#: Smallest pupil segmentation worth reporting, in pixels. Below this the equivalent
#: radius is carried by a handful of pixels and rounds to noise.
MINIMUM_PUPIL_AREA_PX = 9

#: An iris smaller than this is too coarse for a pupil to be measured inside it: at ten
#: pixels of iris radius one pixel of error in the pupil's equivalent radius is already a
#: tenth of the reading, and the millimetre figure inherits it. The aperture survives at
#: smaller sizes because it is a ratio of two extents that are both many pixels long, so a
#: distant face still yields an aperture and simply yields no pupil.
MINIMUM_IRIS_RADIUS_FOR_PUPIL_PX = 10.0

#: A pupil cannot fill its own iris. A segmentation this close to the iris radius means the
#: two did not separate, and no pupil is reported.
PUPIL_IRIS_LIMIT = 0.9

#: Below this height-over-width the lids have met over the iris and the eye counts as
#: closed. An eye open even slightly keeps a visible band of iris wider than it is tall,
#: so this sits well below any aperture a patient holds deliberately.
CLOSED_APERTURE_RATIO = 0.18

#: The aperture ratio an eye reaches once the lids clear the iris entirely. The measure
#: cannot see past this and says so rather than reporting an opening it inferred.
APERTURE_CEILING = 1.0

#: Contrast-limited equalisation makes the iris-to-sclera step survive a face lit from one
#: side. The tile is small because an eye window is small.
_CLAHE = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))

_LEVELS = np.arange(256, dtype=float)


@dataclass(frozen=True)
class EyeReading:
    """One eye in one frame."""

    #: An iris was segmented in the window.
    found: bool
    #: The lids were far enough apart for the measures below to mean anything.
    open: bool
    #: Iris centre, in pixels within the eye window.
    centre: tuple[float, float] = (0.0, 0.0)
    #: Horizontal half-width of the visible iris. The ruler.
    iris_radius_px: float = 0.0
    #: Visible iris height over visible iris width. The aperture.
    aperture_ratio: float = 0.0
    pupil_radius_px: float = 0.0
    #: Millimetres, from the iris ruler. Zero when no pupil separated from the iris.
    pupil_diameter_mm: float = 0.0
    #: Pupil radius over iris radius.
    pupil_iris_ratio: float = 0.0
    #: Where the iris centre sat in the window, as a fraction of its width and height.
    #: Carried per frame so the dispersion over the window can be taken later.
    gaze: tuple[float, float] = (0.0, 0.0)

    @property
    def measurable(self) -> bool:
        return self.found and self.open and self.iris_radius_px >= schema.MINIMUM_IRIS_RADIUS_PX


CLOSED = EyeReading(found=False, open=False)


def _iris_threshold(window: np.ndarray) -> float:
    """The level below which a pixel of an eye window is iris, pupil or lash.

    Otsu's method is used, but for three classes rather than two, and the reason is worth
    stating because it decides whether any of the measurements mean anything. An eye
    window holds three populations: the iris around 60 of 255, the skin of the lids around
    160, and the sclera above 200. The widest gap in that histogram is between skin and
    sclera, so the ordinary two-class threshold splits there and calls the lids dark, which
    lumps the iris in with half the face. Running the method a second time over the dark
    side is not a fix either — where the first split already isolated the iris, the second
    one goes on to separate the pupil from it and the iris ruler collapses onto the pupil.

    So both thresholds are searched for together, over the whole 256-bin histogram, and the
    lower one is returned. That is the iris-to-skin boundary wherever the gaps happen to
    fall. At 256 levels the search is 32 640 pairs of prefix sums and costs nothing.

    A share of the darkest pixels is not used anywhere in this module. Taking a fixed share
    of the iris as the pupil hands that share straight back as the answer whatever the
    pupil is doing, and taking a fixed share of the window as the iris makes the aperture
    depend on how much of the window the lids have covered.
    """
    histogram = np.bincount(window.ravel(), minlength=256).astype(float)
    total = histogram.sum()
    if total <= 0:
        return 0.0
    probability = histogram / total
    weight = np.cumsum(probability)
    moment = np.cumsum(probability * _LEVELS)

    # Class weights and moments for every ordered pair of thresholds at once. Rows are the
    # lower threshold, columns the upper.
    low, high = np.triu_indices(256, k=1)
    w0, w1, w2 = weight[low], weight[high] - weight[low], 1.0 - weight[high]
    m0, m1, m2 = moment[low], moment[high] - moment[low], moment[-1] - moment[high]

    with np.errstate(divide="ignore", invalid="ignore"):
        # Maximising the between-class variance is the same as maximising this sum, since
        # the total mean is fixed. Empty classes are excluded rather than regularised.
        variance = np.where(w0 > 0, m0**2 / w0, 0.0)
        variance += np.where(w1 > 0, m1**2 / w1, 0.0)
        variance += np.where(w2 > 0, m2**2 / w2, 0.0)
    return float(low[int(np.argmax(variance))])


def _otsu(values: np.ndarray) -> float:
    """Two-class Otsu threshold over the given pixels.

    They are passed as a single row, which is legitimate because the method reads nothing
    but the histogram, and a row of the iris has the same histogram as the disc it came
    from. Two classes are right here: inside the iris there is iris and there is pupil.
    """
    cut, _ = cv2.threshold(
        values.reshape(1, -1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return float(cut)


def _components(mask: np.ndarray):
    count, _, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    return count, stats, centroids


def _pick_iris(
    mask: np.ndarray,
    expected_radius_px: float | None = None,
    tolerance: float = IRIS_WIDTH_TOLERANCE,
):
    """The component of `mask` that best looks like an iris.

    Candidates are scored on how close their centroid sits to the middle of the window and
    on how solidly they fill their own bounding box, not purely on size. The largest dark
    component in an eye window is quite often the lash line along its top edge, which is
    big, off-centre and hollow.

    `expected_radius_px` is this patient's own iris half-width, measured during
    calibration. Where it is known it is a hard filter rather than part of the score —
    see IRIS_WIDTH_TOLERANCE for why that matters.
    """
    count, stats, centroids = _components(mask)
    if count <= 1:
        return None

    height, width = mask.shape
    window_area = float(height * width)
    middle = np.array([width / 2.0, height / 2.0])
    reach = float(np.hypot(width, height)) / 2

    best, best_score = None, -1.0
    for index in range(1, count):
        _, _, box_width, box_height, area = (int(value) for value in stats[index])
        if box_width == 0 or box_height == 0:
            continue
        if not IRIS_AREA_SHARE[0] <= area / window_area <= IRIS_AREA_SHARE[1]:
            continue
        if expected_radius_px:
            if abs(box_width / 2 - expected_radius_px) > expected_radius_px * tolerance:
                continue
        elif box_width > width * IRIS_WINDOW_SHARE_LIMIT:
            continue
        aspect = box_width / box_height
        if not 1.0 / IRIS_TALL_LIMIT <= aspect <= IRIS_WIDE_LIMIT:
            continue
        centroid = (float(centroids[index][0]), float(centroids[index][1]))
        closeness = 1.0 - min(1.0, float(np.linalg.norm(np.array(centroid) - middle)) / reach)
        fill = area / float(box_width * box_height)
        score = closeness * 2.0 + fill
        if score > best_score:
            best_score = score
            best = (box_width, box_height, centroid)
    return best


def _pupil(
    window: np.ndarray,
    iris_mask: np.ndarray,
    centre: tuple[float, float],
    iris_radius: float,
) -> float:
    """Pupil radius in pixels, measured only within the iris itself.

    `iris_mask` matters as much as the disc does. A narrowed eye has lid skin crossing the
    disc, and skin is far brighter than iris — so a threshold taken over the disc would
    separate lid from iris and return the whole visible iris as the pupil, growing the
    reading at exactly the moment the patient squints. Intersecting with the mask leaves
    only iris pixels in the histogram, and the split then falls where the pupil is.

    Returns 0.0 when no plausible pupil separates, which happens with a dark iris in low
    light. A pupil that cannot be distinguished is absent rather than assumed to be some
    default size.
    """
    height, width = window.shape
    grid_y, grid_x = np.ogrid[:height, :width]
    # A little inside the iris edge, so the limbus and the lash shadow stay out of the
    # histogram the threshold is taken from.
    radius = iris_radius * 0.85
    inside = iris_mask & (
        (grid_x - centre[0]) ** 2 + (grid_y - centre[1]) ** 2 <= radius**2
    )
    values = window[inside]
    if values.size < 20:
        return 0.0

    mask = inside & (window <= _otsu(values))
    count, stats, _ = _components(mask)
    if count <= 1:
        return 0.0
    area = float(max(int(stats[index][4]) for index in range(1, count)))
    if area < MINIMUM_PUPIL_AREA_PX:
        return 0.0

    # Equivalent radius of a disc of the same area, which is steadier than a bounding box
    # on a pupil partly covered by a corneal reflection.
    pupil_radius = float(np.sqrt(area / np.pi))
    if pupil_radius >= iris_radius * PUPIL_IRIS_LIMIT:
        return 0.0
    return pupil_radius


def measure(
    window: np.ndarray,
    expected_radius_px: float | None = None,
    tolerance: float = IRIS_WIDTH_TOLERANCE,
) -> EyeReading:
    """Read one eye from a grayscale window framed on it.

    `expected_radius_px` is the iris half-width expected for this patient, with the band
    around it that a candidate has to fall inside. Pass it: without it a closed eye and an
    eyebrow are hard to tell apart.
    """
    if window.size == 0 or min(window.shape) < 8:
        return CLOSED

    equalised = _CLAHE.apply(window)
    # A light blur only: every pixel of width this adds to the dark region is a pixel of
    # error in the iris ruler that every millimetre figure is then scaled by.
    smoothed = cv2.GaussianBlur(equalised, (3, 3), 0)

    mask = smoothed <= _iris_threshold(smoothed)
    # Close the pinhole left by the corneal reflection, which otherwise splits the iris
    # into a ring of fragments none of which passes the area test.
    mask = cv2.morphologyEx(
        mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
    ).astype(bool)

    found = _pick_iris(mask, expected_radius_px, tolerance)
    if found is None:
        return CLOSED

    box_width, box_height, centroid = found
    iris_radius = box_width / 2.0
    aperture = min(box_height / box_width, APERTURE_CEILING)
    if aperture < CLOSED_APERTURE_RATIO:
        # The lids have met over the iris. An iris was still found, which is what separates
        # this from a window with no eye in it at all.
        return EyeReading(found=True, open=False, aperture_ratio=round(aperture, 4))

    pupil_radius = (
        _pupil(smoothed, mask, centroid, iris_radius)
        if iris_radius >= MINIMUM_IRIS_RADIUS_FOR_PUPIL_PX
        else 0.0
    )
    scale_mm = schema.IRIS_DIAMETER_MM / box_width if box_width else 0.0
    height, width = window.shape
    return EyeReading(
        found=True,
        open=True,
        centre=centroid,
        iris_radius_px=iris_radius,
        aperture_ratio=round(aperture, 4),
        pupil_radius_px=pupil_radius,
        pupil_diameter_mm=round(2 * pupil_radius * scale_mm, 3),
        pupil_iris_ratio=round(pupil_radius / iris_radius, 4) if iris_radius else 0.0,
        gaze=(round(centroid[0] / width, 4), round(centroid[1] / height, 4)),
    )
