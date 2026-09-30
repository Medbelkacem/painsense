"""Pain categories, as mechanism, time course and clinical setting.

An assessment can carry several of these at once, and the platform never forces one.
`group` separates the three axes so a mechanism is never presented as competing with a
time course: acute neuropathic postoperative pain is one plausible combination.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PainType:
    code: str
    label: str
    group: str
    parent: str | None = None
    description: str = ""


PAIN_TYPES = (
    PainType(
        "NOCICEPTIVE",
        "Nociceptive",
        "MECHANISM",
        description="Arising from actual or threatened damage to non-neural tissue.",
    ),
    PainType("NOCICEPTIVE_SOMATIC", "Somatic", "MECHANISM", "NOCICEPTIVE"),
    PainType("NOCICEPTIVE_VISCERAL", "Visceral", "MECHANISM", "NOCICEPTIVE"),
    PainType(
        "NEUROPATHIC",
        "Neuropathic",
        "MECHANISM",
        description="Caused by a lesion or disease of the somatosensory nervous system.",
    ),
    PainType("NEUROPATHIC_PERIPHERAL", "Peripheral neuropathic", "MECHANISM", "NEUROPATHIC"),
    PainType("NEUROPATHIC_RADICULAR", "Radicular", "MECHANISM", "NEUROPATHIC"),
    PainType("NEUROPATHIC_NEURALGIA", "Neuralgia", "MECHANISM", "NEUROPATHIC"),
    PainType(
        "NEUROPATHIC_POLYNEUROPATHY", "Polyneuropathy-associated", "MECHANISM", "NEUROPATHIC"
    ),
    PainType(
        "NOCIPLASTIC",
        "Nociplastic",
        "MECHANISM",
        description=(
            "Arising from altered nociception without clear evidence of tissue damage or "
            "of a lesion of the somatosensory system. Recorded as a category only; the "
            "platform does not assert this mechanism."
        ),
    ),
    PainType("INFLAMMATORY", "Inflammatory", "MECHANISM"),
    PainType("MUSCULOSKELETAL", "Musculoskeletal", "MECHANISM"),
    PainType("MIXED", "Mixed", "MECHANISM"),
    PainType("ACUTE", "Acute", "COURSE"),
    PainType("CHRONIC", "Chronic", "COURSE"),
    PainType("RECURRENT", "Recurrent", "COURSE"),
    PainType("TRAUMATIC", "Traumatic", "SETTING"),
    PainType("POSTOPERATIVE", "Postoperative", "SETTING"),
    PainType("CANCER_RELATED", "Cancer-related", "SETTING"),
)

BY_CODE = {pain_type.code: pain_type for pain_type in PAIN_TYPES}
GROUPS = ("MECHANISM", "COURSE", "SETTING")
