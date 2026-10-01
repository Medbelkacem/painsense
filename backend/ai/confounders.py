from dataclasses import dataclass

from backend.ai import features
from knowledge import confounders as confounder_kb
from knowledge import profiles, reference_ranges, rules
from knowledge.context import ClinicalContext

WIDENING_PER_AFFECTED_VITAL = 0.12
MAX_WIDENING = 0.5

RECORDED = "RECORDED"
FROM_PROFILE = "FROM_PROFILE"


@dataclass
class ContextNote:
    code: str
    label: str
    explanation: str
    affected_vitals: list[str]
    vitals_deranged: list[str]
    # RECORDED where the clinician ticked it, FROM_PROFILE where the population it belongs
    # to makes it worth considering whether or not it was ticked.
    source: str = RECORDED


@dataclass
class ContextAnalysis:
    notes: list[ContextNote]
    widening: float
    # The share of the interval attributable to the profile alone, reported separately so
    # the interface can say which part of the uncertainty comes from the population and
    # which from what was recorded at this visit.
    profile_widening: float = 0.0
    fever_hr_allowance: float = 0.0

    @property
    def any_vital_contested(self) -> bool:
        return any(note.vitals_deranged for note in self.notes)

    @property
    def recorded(self) -> list[ContextNote]:
        return [note for note in self.notes if note.source == RECORDED]

    @property
    def suggested(self) -> list[ContextNote]:
        return [note for note in self.notes if note.source == FROM_PROFILE]


def analyse(
    ctx: ClinicalContext, influential_features: list[str] | None = None
) -> ContextAnalysis:
    influential = set(influential_features or features.VITAL_FEATURES)
    deranged = set(rules.deranged_for(ctx))

    applicable = profiles.applicable_to(ctx)
    from_profile = profiles.confounders_for(applicable) - ctx.confounders

    notes = []
    contested = set()
    for code in sorted(ctx.confounders | from_profile):
        entry = confounder_kb.BY_CODE.get(code)
        if entry is None:
            continue
        affected = [vital for vital in entry.affects if ctx.vitals.get(vital) is not None]
        abnormal = [vital for vital in affected if vital in deranged]
        recorded = code not in from_profile
        notes.append(
            ContextNote(
                code=entry.code,
                label=entry.label,
                explanation=entry.note,
                affected_vitals=affected,
                vitals_deranged=abnormal,
                source=RECORDED if recorded else FROM_PROFILE,
            )
        )
        # Only a confounder the clinician actually recorded widens the interval. One the
        # profile merely raises is a prompt to check, and the profile has already paid for
        # itself through its own penalty.
        if recorded:
            contested.update(vital for vital in abnormal if vital in influential)

    from_recorded = min(len(contested) * WIDENING_PER_AFFECTED_VITAL, MAX_WIDENING)
    from_profile_penalty = profiles.confidence_penalty(applicable)

    return ContextAnalysis(
        notes=notes,
        widening=round(min(from_recorded + from_profile_penalty, MAX_WIDENING), 3),
        profile_widening=round(from_profile_penalty, 3),
        fever_hr_allowance=round(
            reference_ranges.fever_heart_rate_allowance(ctx.vitals.get("temperature_c")), 1
        ),
    )
