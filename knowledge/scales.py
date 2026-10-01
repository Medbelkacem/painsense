"""Pain scales used as the reference a profile is compared against.

Two kinds live here. A self-report scale records what the patient says. An observational
scale records what a clinician sees, and is the reference for a patient who cannot
self-report at all. Both are references, never model inputs: the estimation pipeline
reads neither, which is what keeps the comparison between estimate and reference from
being circular.

Every scale keeps its own range. `normalise` projects a raw score linearly onto the 0-10
axis so that one number can be stored beside estimates taken on another scale, and that
projection is a presentation convenience, not a claim that the two instruments measure
the same thing on the same units. The raw score and the scale that produced it are always
kept alongside it, and metrics are reported per scale as well as pooled.

Sources:

  NRS       Numerical Rating Scale, 0-10 integers. Described in section 6 of the
            challenge brief.
  VAS       Visual Analogue Scale, a 100 mm line converted to 0-10.
  FPS_R     Hicks C.L., von Baeyer C.L., Spafford P.A., van Korlaar I., Goodenough B.,
            "The Faces Pain Scale - Revised: toward a common metric in pediatric pain
            measurement", Pain, 2001, 93(2), 173-183.
  NIPS      Lawrence J., Alcock D., McGrath P., Kay J., MacMurray S.B., Dulberg C.,
            "The development of a tool to assess neonatal pain", Neonatal Network, 1993,
            12(6), 59-66.
  PIPP      Stevens B., Johnston C., Petryshen P., Taddio A., "Premature Infant Pain
            Profile: development and initial validation", Clinical Journal of Pain, 1996,
            12(1), 13-22.
  FLACC     Merkel S.I., Voepel-Lewis T., Shayevitz J.R., Malviya S., "The FLACC: a
            behavioral scale for scoring postoperative pain in young children",
            Pediatric Nursing, 1997, 23(3), 293-297.
  PAINAD    Warden V., Hurley A.C., Volicer L., "Development and psychometric evaluation
            of the Pain Assessment in Advanced Dementia (PAINAD) scale", Journal of the
            American Medical Directors Association, 2003, 4(1), 9-15.
  CPOT      Gelinas C., Fillion L., Puntillo K.A., Viens C., Fortier M., "Validation of
            the Critical-Care Pain Observation Tool in adult patients", American Journal
            of Critical Care, 2006, 15(4), 420-427. Also reference 4 of the brief.
  BPS       Payen J.F., Bru O., Bosson J.L. et al., "Assessing pain in critically ill
            sedated patients by using a behavioral pain scale", Critical Care Medicine,
            2001, 29(12), 2258-2263.

TO VERIFY applies to the per-item anchor wording below. The item sets, their score ranges
and the totals are as published. The one-line anchors are abbreviated for the interface
and are not the full published descriptors, so they must be checked against the original
instrument before any clinical use.
"""

from dataclasses import dataclass

SELF = "SELF"
OBSERVER = "OBSERVER"

NRS = "NRS"
VAS = "VAS"
FPS_R = "FPS_R"
NIPS = "NIPS"
PIPP = "PIPP"
FLACC = "FLACC"
PAINAD = "PAINAD"
CPOT = "CPOT"
BPS = "BPS"


@dataclass(frozen=True)
class Item:
    code: str
    label: str
    minimum: int
    maximum: int
    # Abbreviated anchors, lowest score first. Not the full published descriptors.
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scale:
    code: str
    label: str
    source: str
    kind: str
    minimum: float
    maximum: float
    items: tuple[Item, ...] = ()
    # Integers the patient may pick, for a self-report scale scored by selection.
    steps: tuple[int, ...] = ()
    population: str = ""
    note: str = ""

    @property
    def observational(self) -> bool:
        return self.kind == OBSERVER

    @property
    def item_total_range(self) -> tuple[int, int]:
        return (
            sum(item.minimum for item in self.items),
            sum(item.maximum for item in self.items),
        )


SCALES = (
    Scale(
        NRS,
        "Numerical Rating Scale",
        "NRS",
        SELF,
        0.0,
        10.0,
        steps=tuple(range(11)),
        population="Anyone who can put a number on their pain.",
    ),
    Scale(
        VAS,
        "Visual Analogue Scale",
        "VAS",
        SELF,
        0.0,
        10.0,
        population="As NRS, where a continuous line is preferred to a number.",
        note="Recorded as the converted 0-10 distance rather than as millimetres.",
    ),
    Scale(
        FPS_R,
        "Faces Pain Scale - Revised",
        "FPS_R",
        SELF,
        0.0,
        10.0,
        steps=(0, 2, 4, 6, 8, 10),
        population="Children who recognise faces before they handle numbers.",
        note="Six faces scored 0, 2, 4, 6, 8, 10. Still a self-report.",
    ),
    Scale(
        NIPS,
        "Neonatal Infant Pain Scale",
        "NIPS",
        OBSERVER,
        0.0,
        7.0,
        items=(
            Item("FACIAL_EXPRESSION", "Facial expression", 0, 1, ("Relaxed", "Grimace")),
            Item("CRY", "Cry", 0, 2, ("No cry", "Whimper", "Vigorous cry")),
            Item("BREATHING", "Breathing pattern", 0, 1, ("Relaxed", "Change in breathing")),
            Item("ARMS", "Arms", 0, 1, ("Relaxed", "Flexed or extended")),
            Item("LEGS", "Legs", 0, 1, ("Relaxed", "Flexed or extended")),
            Item(
                "AROUSAL", "State of arousal", 0, 1, ("Sleeping or awake and settled", "Fussy")
            ),
        ),
        population="Newborns.",
    ),
    Scale(
        PIPP,
        "Premature Infant Pain Profile",
        "PIPP",
        OBSERVER,
        0.0,
        21.0,
        items=(
            Item("GESTATIONAL_AGE", "Gestational age", 0, 3),
            Item("BEHAVIOURAL_STATE", "Behavioural state", 0, 3),
            Item("HEART_RATE_CHANGE", "Change in heart rate", 0, 3),
            Item("OXYGEN_SATURATION_CHANGE", "Fall in oxygen saturation", 0, 3),
            Item("BROW_BULGE", "Brow bulge", 0, 3),
            Item("EYE_SQUEEZE", "Eye squeeze", 0, 3),
            Item("NASOLABIAL_FURROW", "Nasolabial furrow", 0, 3),
        ),
        population="Preterm and newborn infants.",
        note=(
            "TO VERIFY: the thresholds that turn an observed heart-rate rise or "
            "saturation fall into a 0-3 score are part of the published instrument and "
            "are not reproduced here, so those two items must be scored by the clinician "
            "from the original tool."
        ),
    ),
    Scale(
        FLACC,
        "Face, Legs, Activity, Cry, Consolability",
        "FLACC",
        OBSERVER,
        0.0,
        10.0,
        items=(
            Item(
                "FACE",
                "Face",
                0,
                2,
                ("No particular expression", "Occasional grimace", "Frequent clenched jaw"),
            ),
            Item(
                "LEGS",
                "Legs",
                0,
                2,
                ("Normal position", "Uneasy or restless", "Kicking or drawn up"),
            ),
            Item(
                "ACTIVITY",
                "Activity",
                0,
                2,
                ("Lying quietly", "Squirming or tense", "Arched or jerking"),
            ),
            Item(
                "CRY",
                "Cry",
                0,
                2,
                ("No cry", "Moans or whimpers", "Crying steadily or screaming"),
            ),
            Item(
                "CONSOLABILITY",
                "Consolability",
                0,
                2,
                ("Content", "Reassured by touch or talking", "Difficult to console"),
            ),
        ),
        population="Infants and young children, roughly 2 months to 7 years.",
    ),
    Scale(
        PAINAD,
        "Pain Assessment in Advanced Dementia",
        "PAINAD",
        OBSERVER,
        0.0,
        10.0,
        items=(
            Item(
                "BREATHING",
                "Breathing independent of vocalisation",
                0,
                2,
                ("Normal", "Occasional laboured breathing", "Noisy laboured breathing"),
            ),
            Item(
                "NEGATIVE_VOCALISATION",
                "Negative vocalisation",
                0,
                2,
                ("None", "Occasional moan or groan", "Repeated calling out or crying"),
            ),
            Item(
                "FACIAL_EXPRESSION",
                "Facial expression",
                0,
                2,
                ("Smiling or inexpressive", "Sad or frowning", "Facial grimacing"),
            ),
            Item(
                "BODY_LANGUAGE",
                "Body language",
                0,
                2,
                ("Relaxed", "Tense or fidgeting", "Rigid, fists clenched, striking out"),
            ),
            Item(
                "CONSOLABILITY",
                "Consolability",
                0,
                2,
                (
                    "No need to console",
                    "Distracted or reassured by voice or touch",
                    "Unable to console",
                ),
            ),
        ),
        population="Adults with advanced dementia or otherwise unable to report.",
    ),
    Scale(
        CPOT,
        "Critical-Care Pain Observation Tool",
        "CPOT",
        OBSERVER,
        0.0,
        8.0,
        items=(
            Item(
                "FACIAL_EXPRESSION",
                "Facial expression",
                0,
                2,
                ("Relaxed", "Tense", "Grimacing"),
            ),
            Item(
                "BODY_MOVEMENTS",
                "Body movements",
                0,
                2,
                ("Absence of movement", "Protection", "Restlessness"),
            ),
            Item(
                "MUSCLE_TENSION",
                "Muscle tension on passive flexion",
                0,
                2,
                ("Relaxed", "Tense or rigid", "Very tense or rigid"),
            ),
            Item(
                "VENTILATOR_OR_VOICE",
                "Ventilator compliance, or vocalisation if extubated",
                0,
                2,
                (
                    "Tolerating or speaking normally",
                    "Coughing but tolerating, or sighing and moaning",
                    "Fighting the ventilator, or crying out",
                ),
            ),
        ),
        population="Adults in critical care, intubated or not.",
    ),
    Scale(
        BPS,
        "Behavioural Pain Scale",
        "BPS",
        OBSERVER,
        3.0,
        12.0,
        items=(
            Item(
                "FACIAL_EXPRESSION",
                "Facial expression",
                1,
                4,
                ("Relaxed", "Partially tightened", "Fully tightened", "Grimacing"),
            ),
            Item(
                "UPPER_LIMBS",
                "Upper limb movements",
                1,
                4,
                (
                    "No movement",
                    "Partially bent",
                    "Fully bent with finger flexion",
                    "Permanently retracted",
                ),
            ),
            Item(
                "VENTILATION_COMPLIANCE",
                "Compliance with ventilation",
                1,
                4,
                (
                    "Tolerating movement",
                    "Coughing but tolerating most of the time",
                    "Fighting the ventilator",
                    "Unable to control ventilation",
                ),
            ),
        ),
        population="Sedated, mechanically ventilated adults.",
        note="Lowest possible total is 3, not 0, which the projection onto 0-10 accounts for.",
    ),
)

BY_CODE = {scale.code: scale for scale in SCALES}
OBSERVATIONAL = tuple(scale.code for scale in SCALES if scale.observational)
SELF_REPORTED = tuple(scale.code for scale in SCALES if scale.kind == SELF)

NRS_MIN = 0.0
NRS_MAX = 10.0


def normalise(scale_code: str, raw: float) -> float:
    """Project a raw score onto the 0-10 axis. A linear projection of the instrument's
    own range: it makes scores storable and comparable in one column, and it is not a
    validated equivalence between instruments."""
    scale = BY_CODE[scale_code]
    span = scale.maximum - scale.minimum
    if span <= 0:
        return NRS_MIN
    fraction = (raw - scale.minimum) / span
    return round(min(max(fraction, 0.0), 1.0) * NRS_MAX, 2)


def total(scale_code: str, items: dict[str, float]) -> float:
    """Sum the scored items of an observational scale, clamped to the scale's range.
    Items that were not scored count as their lowest value, which is how the published
    instruments are totalled when an item cannot be observed."""
    scale = BY_CODE[scale_code]
    if not scale.items:
        raise ValueError(f"{scale_code} is not scored from items")

    running = 0.0
    for item in scale.items:
        given = items.get(item.code)
        value = item.minimum if given is None else float(given)
        running += min(max(value, item.minimum), item.maximum)
    return min(max(running, scale.minimum), scale.maximum)


def unscored_items(scale_code: str, items: dict[str, float]) -> tuple[str, ...]:
    scale = BY_CODE[scale_code]
    return tuple(item.code for item in scale.items if items.get(item.code) is None)
