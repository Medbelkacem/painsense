"""Normalised pain-location taxonomy.

The code is the stable identifier. Labels can be retranslated or reworded, but a code
that an assessment already references must never change meaning.

Laterality is not encoded here: a location plus a side is recorded on the assessment, so
"left knee" does not need a code of its own.
"""

from dataclasses import dataclass

REGIONS = (
    ("HEAD", "Head and face"),
    ("NECK", "Neck"),
    ("CHEST", "Chest"),
    ("BACK", "Back"),
    ("ABDOMEN", "Abdomen"),
    ("PELVIS", "Pelvis and genital region"),
    ("UPPER_LIMB", "Upper limb"),
    ("LOWER_LIMB", "Lower limb"),
    ("SYSTEMIC", "Generalised or unspecified"),
)


@dataclass(frozen=True)
class Location:
    code: str
    label: str
    region: str
    parent: str | None = None


LOCATIONS = (
    Location("HEAD", "Head", "HEAD"),
    Location("FOREHEAD", "Forehead", "HEAD", "HEAD"),
    Location("TEMPLE", "Temple", "HEAD", "HEAD"),
    Location("OCCIPUT", "Occipital region", "HEAD", "HEAD"),
    Location("EYE", "Eye and periorbital region", "HEAD", "HEAD"),
    Location("EAR", "Ear", "HEAD", "HEAD"),
    Location("FACE", "Face", "HEAD", "HEAD"),
    Location("JAW", "Jaw and temporomandibular joint", "HEAD", "HEAD"),
    Location("TEETH", "Teeth", "HEAD", "HEAD"),
    Location("NECK", "Neck", "NECK"),
    Location("CHEST", "Chest", "CHEST"),
    Location("CHEST_CENTRAL", "Central chest", "CHEST", "CHEST"),
    Location("CHEST_LEFT", "Left chest", "CHEST", "CHEST"),
    Location("CHEST_RIGHT", "Right chest", "CHEST", "CHEST"),
    Location("CHEST_DIFFUSE", "Diffuse chest", "CHEST", "CHEST"),
    Location("BREAST", "Breast", "CHEST", "CHEST"),
    Location("BACK", "Back", "BACK"),
    Location("BACK_CERVICAL", "Cervical spine", "BACK", "BACK"),
    Location("BACK_THORACIC", "Thoracic spine (upper back)", "BACK", "BACK"),
    Location("BACK_LUMBAR", "Lumbar spine (lower back)", "BACK", "BACK"),
    Location("BACK_SACRAL", "Sacral region", "BACK", "BACK"),
    Location("ABDOMEN", "Abdomen", "ABDOMEN"),
    Location("ABD_EPIGASTRIC", "Epigastric", "ABDOMEN", "ABDOMEN"),
    Location("ABD_RUQ", "Right upper quadrant", "ABDOMEN", "ABDOMEN"),
    Location("ABD_LUQ", "Left upper quadrant", "ABDOMEN", "ABDOMEN"),
    Location("ABD_PERIUMBILICAL", "Periumbilical", "ABDOMEN", "ABDOMEN"),
    Location("ABD_RLQ", "Right lower quadrant", "ABDOMEN", "ABDOMEN"),
    Location("ABD_LLQ", "Left lower quadrant", "ABDOMEN", "ABDOMEN"),
    Location("ABD_SUPRAPUBIC", "Suprapubic", "ABDOMEN", "ABDOMEN"),
    Location("ABD_DIFFUSE", "Diffuse abdominal", "ABDOMEN", "ABDOMEN"),
    Location("PELVIS", "Pelvis", "PELVIS"),
    Location("GENITAL", "Genital region", "PELVIS", "PELVIS"),
    Location("SHOULDER", "Shoulder", "UPPER_LIMB"),
    Location("ARM", "Arm", "UPPER_LIMB"),
    Location("ELBOW", "Elbow", "UPPER_LIMB"),
    Location("FOREARM", "Forearm", "UPPER_LIMB"),
    Location("WRIST", "Wrist", "UPPER_LIMB"),
    Location("HAND", "Hand", "UPPER_LIMB"),
    Location("FINGER", "Finger", "UPPER_LIMB"),
    Location("HIP", "Hip", "LOWER_LIMB"),
    Location("THIGH", "Thigh", "LOWER_LIMB"),
    Location("KNEE", "Knee", "LOWER_LIMB"),
    Location("LEG", "Leg", "LOWER_LIMB"),
    Location("ANKLE", "Ankle", "LOWER_LIMB"),
    Location("FOOT", "Foot", "LOWER_LIMB"),
    Location("TOE", "Toe", "LOWER_LIMB"),
    Location("GENERALIZED", "Generalised", "SYSTEMIC"),
    Location("UNSPECIFIED", "Other or unspecified site", "SYSTEMIC"),
)

BY_CODE = {location.code: location for location in LOCATIONS}

SIDES = ("LEFT", "RIGHT", "BILATERAL", "MIDLINE", "NOT_APPLICABLE")


def regions_of(codes: list[str]) -> set[str]:
    return {BY_CODE[code].region for code in codes if code in BY_CODE}


def children(code: str) -> tuple[Location, ...]:
    return tuple(location for location in LOCATIONS if location.parent == code)
