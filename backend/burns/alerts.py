"""Flags that ask a clinician to look at a burn assessment.

These are not triage decisions and they are not emergency calls. Each rule states what it
observed and why that warrants review, and the module deliberately has no rule that
clears a patient: nothing here produces "no concerns", because the absence of a flag is
not a clinical opinion.

The thresholds are the ones burn services commonly use for referral. They are referral
prompts, not diagnoses, and a burn below every threshold here can still need a burns unit.

`UNCERTAIN` depth and unknown age raise flags of their own. An assessment that has not
been completed should not look the same as one that was completed and found nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from database.models import AlertSeverity
from knowledge import burns

REVIEW = AlertSeverity.REVIEW
URGENT = AlertSeverity.URGENT_REVIEW

#: Referral thresholds by age. Children and older adults tolerate a smaller burn less
#: well, which is why a single percentage would be the wrong rule.
ADULT_EXTENT_THRESHOLD = 10.0
CHILD_EXTENT_THRESHOLD = 5.0
OLDER_ADULT_AGE = 65


@dataclass(frozen=True)
class Alert:
    code: str
    severity: AlertSeverity
    message: str
    detail: dict

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "detail": self.detail,
        }


def evaluate(
    *,
    regions: list[dict],
    total_percent: float | None,
    age_years: float | None,
    cause: str,
    enclosed_space: bool | None = None,
    airway_symptoms: list[str] | None = None,
    provisional: bool = False,
) -> list[Alert]:
    """Every flag this assessment raises.

    `regions` are dicts with `region_code`, `depth` and `circumferential`, which is what
    both the stored rows and an unsaved draft can supply.
    """
    found: list[Alert] = []
    airway_symptoms = airway_symptoms or []

    found.extend(_extent(total_percent, age_years))
    found.extend(_depth(regions))
    found.extend(_site(regions))
    found.extend(_circumferential(regions))
    found.extend(_cause(cause))
    found.extend(_airway(cause, enclosed_space, airway_symptoms))
    found.extend(_completeness(age_years, provisional))
    return found


def _extent(total_percent: float | None, age_years: float | None) -> list[Alert]:
    if total_percent is None:
        return []
    child = burns.is_child(age_years)
    older = age_years is not None and age_years >= OLDER_ADULT_AGE
    threshold = CHILD_EXTENT_THRESHOLD if child or older else ADULT_EXTENT_THRESHOLD
    if total_percent < threshold:
        return []
    group = "a child" if child else "an older adult" if older else "an adult"
    return [
        Alert(
            "EXTENT",
            URGENT if total_percent >= threshold * 2 else REVIEW,
            f"The estimated burned surface is {total_percent:g}%, at or above the {threshold:g}% "
            f"commonly used as a referral prompt for {group}.",
            {"total_percent": total_percent, "threshold": threshold, "age_years": age_years},
        )
    ]


def _depth(regions: list[dict]) -> list[Alert]:
    deep = [
        entry["region_code"]
        for entry in regions
        if entry.get("depth") in (burns.DEEP_PARTIAL, burns.FULL_THICKNESS)
    ]
    if not deep:
        return []
    full = [entry["region_code"] for entry in regions if entry.get("depth") == burns.FULL_THICKNESS]
    return [
        Alert(
            "DEPTH",
            URGENT if full else REVIEW,
            (
                "A full-thickness burn is recorded. These do not heal by themselves and "
                "need surgical assessment."
                if full
                else "A deep partial-thickness burn is recorded, which warrants review of "
                "whether it will heal without surgery."
            ),
            {"regions": sorted(set(deep)), "full_thickness": sorted(set(full))},
        )
    ]


def _site(regions: list[dict]) -> list[Alert]:
    involved = sorted(
        {
            entry["region_code"]
            for entry in regions
            if entry["region_code"] in burns.HIGH_RISK_REGIONS
        }
    )
    if not involved:
        return []
    labels = [burns.REGION_BY_CODE[code].label for code in involved]
    return [
        Alert(
            "HIGH_RISK_SITE",
            URGENT,
            "The burn involves "
            + ", ".join(labels)
            + ". A burn at these sites threatens function, the airway or continence "
            "whatever its size, and is a referral prompt on site alone.",
            {"regions": involved},
        )
    ]


def _circumferential(regions: list[dict]) -> list[Alert]:
    involved = sorted(
        {entry["region_code"] for entry in regions if entry.get("circumferential")}
    )
    if not involved:
        return []
    return [
        Alert(
            "CIRCUMFERENTIAL",
            URGENT,
            "A circumferential burn is recorded at "
            + ", ".join(burns.REGION_BY_CODE[code].label for code in involved)
            + ". These can restrict circulation or breathing as swelling develops and "
            "need review now rather than at the next dressing change.",
            {"regions": involved},
        )
    ]


def _cause(cause: str) -> list[Alert]:
    if cause not in burns.DECEPTIVE_CAUSES:
        return []
    detail = {
        "ELECTRICAL": (
            "An electrical injury can leave a small surface wound over extensive deep "
            "damage, and carries a cardiac risk the skin gives no sign of."
        ),
        "CHEMICAL": (
            "A chemical injury can continue to burn after the patient is seen, and its "
            "final depth is often greater than it first appears."
        ),
    }[cause]
    return [Alert("CAUSE", URGENT, detail, {"cause": cause})]


def _airway(cause: str, enclosed_space: bool | None, symptoms: list[str]) -> list[Alert]:
    reasons = []
    if enclosed_space:
        reasons.append("the injury happened in an enclosed space")
    if cause == "FLAME":
        reasons.append("the cause was flame")
    if symptoms:
        reasons.append("reported symptoms: " + ", ".join(sorted(symptoms)))
    if not symptoms and len(reasons) < 2:
        return []
    return [
        Alert(
            "AIRWAY",
            URGENT,
            "Features associated with inhalation injury are present ("
            + "; ".join(reasons)
            + "). This is a prompt for airway assessment by a clinician, not a finding: "
            "nothing here examines the airway.",
            {"enclosed_space": enclosed_space, "symptoms": sorted(symptoms), "cause": cause},
        )
    ]


def _completeness(age_years: float | None, provisional: bool) -> list[Alert]:
    found = []
    if provisional:
        found.append(
            Alert(
                "DEPTH_UNDECIDED",
                REVIEW,
                "At least one burned area has no decided depth, so the surface area total "
                "is provisional and the depth-based flags above may be incomplete.",
                {},
            )
        )
    if age_years is None:
        found.append(
            Alert(
                "AGE_UNKNOWN",
                REVIEW,
                "The patient's age was not recorded. The surface area chart and the extent "
                "threshold both depend on it, and adult values were assumed.",
                {},
            )
        )
    return found
