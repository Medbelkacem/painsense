"""How the recorded profile changes the reading of an estimate.

This is the part a clinician sees: which population the patient was read as, which bands
the vitals were compared against, which scale the estimate should be checked against, and
whether the patient could be asked at all. It produces no number of its own; it says what
the number means for this patient.
"""

from dataclasses import dataclass, field

from knowledge import profiles, reference_ranges, scales
from knowledge.context import ClinicalContext


@dataclass
class BandReading:
    vital: str
    low: float
    high: float
    value: float | None
    # Where the reading sits in the band: 0 at the bottom, 1 at the top, outside those
    # when the reading is outside the band.
    position: float | None
    within: bool
    unverified: bool


@dataclass
class PopulationReading:
    primary: str
    primary_label: str
    modifiers: tuple[str, ...] = ()
    modifier_labels: tuple[str, ...] = ()
    band: str = reference_ranges.ADULT
    band_label: str = ""
    band_source: str = ""
    can_self_report: bool = True
    reference_scale: str | None = None
    reference_scale_label: str = ""
    reference_is_observational: bool = False
    alternative_scales: tuple[str, ...] = ()
    priority_signals: tuple[str, ...] = ()
    signals_not_available: tuple[str, ...] = ()
    pregnancy_trimester: int | None = None
    expected_pain: bool = False
    prefers_own_history: bool = False
    baseline_source: str | None = None
    baseline_points: int = 0
    confidence_penalty: float = 0.0
    bands: list[BandReading] = field(default_factory=list)
    # Fields whose band could not be traced to a named source, so the interface can say so
    # rather than presenting the comparison as established.
    unverified_vitals: tuple[str, ...] = ()
    interpretation: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "primary_label": self.primary_label,
            "modifiers": list(self.modifiers),
            "modifier_labels": list(self.modifier_labels),
            "band": self.band,
            "band_label": self.band_label,
            "band_source": self.band_source,
            "can_self_report": self.can_self_report,
            "reference_scale": self.reference_scale,
            "reference_scale_label": self.reference_scale_label,
            "reference_is_observational": self.reference_is_observational,
            "alternative_scales": list(self.alternative_scales),
            "priority_signals": list(self.priority_signals),
            "signals_not_available": list(self.signals_not_available),
            "pregnancy_trimester": self.pregnancy_trimester,
            "expected_pain": self.expected_pain,
            "prefers_own_history": self.prefers_own_history,
            "baseline_source": self.baseline_source,
            "baseline_points": self.baseline_points,
            "confidence_penalty": self.confidence_penalty,
            "bands": [
                {
                    "vital": entry.vital,
                    "low": entry.low,
                    "high": entry.high,
                    "value": entry.value,
                    "position": entry.position,
                    "within": entry.within,
                    "unverified": entry.unverified,
                }
                for entry in self.bands
            ],
            "unverified_vitals": list(self.unverified_vitals),
            "interpretation": self.interpretation,
            "notes": list(self.notes),
        }


def read(ctx: ClinicalContext) -> PopulationReading:
    primary = profiles.primary_of(ctx)
    applicable = profiles.applicable_to(ctx)
    modifiers = tuple(p for p in applicable if p.kind == profiles.MODIFIER)
    band = profiles.band_for(primary, ctx.age)
    ranges = profiles.normal_ranges(ctx)

    readings = []
    for vital, (low, high) in sorted(ranges.items()):
        value = ctx.vitals.get(vital)
        position = None
        if value is not None and high > low:
            position = round((value - low) / (high - low), 3)
        readings.append(
            BandReading(
                vital=vital,
                low=low,
                high=high,
                value=value,
                position=position,
                within=value is None or low <= value <= high,
                unverified=vital in band.unverified,
            )
        )

    scale_code = profiles.reference_scale_for(primary)
    scale = scales.BY_CODE[scale_code]

    notes = [profile.note for profile in applicable if profile.note]
    if ctx.pregnancy_trimester is not None and reference_ranges.PREGNANCY_UNVERIFIED:
        notes.append(
            "The per-trimester shift applied to the heart-rate band is marked "
            f"{reference_ranges.TO_VERIFY} in the reference configuration."
        )
    if not primary.can_self_report:
        notes.append(
            f"This patient cannot be asked for a score. {scale.label} scored by the "
            "clinician is the reference the estimate is compared against."
        )
    if profiles.prefers_own_history(applicable) and not ctx.baseline_vitals:
        notes.append(
            "This profile is read against the patient's own earlier readings, and there "
            "are none yet. Record a calibration at rest, or a second visit, before "
            "reading much into the comparison."
        )

    return PopulationReading(
        primary=primary.code,
        primary_label=primary.label,
        modifiers=tuple(p.code for p in modifiers),
        modifier_labels=tuple(p.label for p in modifiers),
        band=band.code,
        band_label=band.label,
        band_source=band.source,
        can_self_report=primary.can_self_report,
        reference_scale=scale_code,
        reference_scale_label=scale.label,
        reference_is_observational=scale.observational,
        alternative_scales=primary.alternative_scales,
        priority_signals=primary.priority_signals,
        signals_not_available=profiles.signals_not_available(applicable),
        pregnancy_trimester=ctx.pregnancy_trimester,
        expected_pain=ctx.expected_pain,
        prefers_own_history=profiles.prefers_own_history(applicable),
        baseline_source=ctx.baseline_source,
        baseline_points=ctx.baseline_points,
        confidence_penalty=profiles.confidence_penalty(applicable),
        bands=readings,
        unverified_vitals=band.unverified,
        interpretation=primary.interpretation,
        notes=notes,
    )
