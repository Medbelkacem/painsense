"""Reading vital signs in context.

The challenge statement is explicit that a raised heart rate is not proof of pain, and this
module is where the platform acts on that rather than only saying it. When the clinician has
recorded a context that can move a vital sign, and the model leaned on that vital sign, two
things happen: the explanation names the alternative explanation, and the uncertainty
interval widens, because the reading supports two stories at once.

It does not subtract anything from the estimate. There is no evidence base here for "remove
0.4 points because the patient is anxious", and inventing one would be worse than being
honest about the ambiguity.
"""

from dataclasses import dataclass

from app.ai import features
from app.knowledge import confounders as confounder_kb
from app.knowledge import rules
from app.knowledge.context import ClinicalContext

# Each affected vital that the model actually leaned on widens the interval by this much,
# relative to its own width.
WIDENING_PER_AFFECTED_VITAL = 0.12
MAX_WIDENING = 0.5


@dataclass
class ContextNote:
    code: str
    label: str
    explanation: str
    affected_vitals: list[str]
    vitals_deranged: list[str]


@dataclass
class ContextAnalysis:
    notes: list[ContextNote]
    widening: float

    @property
    def any_vital_contested(self) -> bool:
        return any(note.vitals_deranged for note in self.notes)


def analyse(
    ctx: ClinicalContext, influential_features: list[str] | None = None
) -> ContextAnalysis:
    """Describe how the recorded context bears on the vital signs the model used."""
    influential = set(influential_features or features.VITAL_FEATURES)
    deranged = set(rules.deranged_vitals(ctx.vitals))

    notes = []
    contested = set()
    for code in sorted(ctx.confounders):
        entry = confounder_kb.BY_CODE.get(code)
        if entry is None:
            continue
        affected = [vital for vital in entry.affects if ctx.vitals.get(vital) is not None]
        abnormal = [vital for vital in affected if vital in deranged]
        notes.append(
            ContextNote(
                code=entry.code,
                label=entry.label,
                explanation=entry.note,
                affected_vitals=affected,
                vitals_deranged=abnormal,
            )
        )
        contested.update(vital for vital in abnormal if vital in influential)

    widening = min(len(contested) * WIDENING_PER_AFFECTED_VITAL, MAX_WIDENING)
    return ContextAnalysis(notes=notes, widening=round(widening, 3))
