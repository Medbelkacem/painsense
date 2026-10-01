"""Whether an acquired dataset can actually train this platform's model.

This is the gate the brief calls "trigger training only if the dataset is suitable", and
almost everything that comes through the pipeline fails it. That is the correct outcome,
not a defect: the model in `app.ai` estimates a 0-10 pain rating from a clinician's
examination of one patient, and WHO indicator tables, CDC notifiable-disease counts and
Kaggle migraine questionnaires are simply not that. Saying so in a recorded, readable
verdict is more useful than quietly training on whatever arrives.

Four conditions have to hold, and each is checked against measurements taken from the
stored file rather than against the publisher's description:

*Rows describe people.* An aggregate table has no per-patient target to learn, whatever
its title says.

*There is a pain rating.* A named rating column whose values sit on a recognised scale.
A binary pain/no-pain flag is reported as present but insufficient for the regression
task, which is a different answer from having no target at all.

*Subjects can be separated.* Without a subject identifier, a random split puts the same
person in train and test and the resulting score is leakage, not performance. The pain
pipeline next door groups its splits by patient for the same reason.

*There is enough of it.* Enough rows and enough distinct subjects for a grouped split to
leave something in each fold.

What a passing dataset trains is its *own* baseline, not the platform's clinical model.
`app.ai.training` learns from a clinician's examination expressed in this platform's
feature schema; an external table's columns are its publisher's and mean something else.
So `app.sync.training` fits a separate regressor on that dataset's own numeric columns,
records it as a model version that is never activated, and leaves the clinical model
alone. `clinically_usable` says so explicitly, because a good score on a Kaggle table is
not evidence about this platform's bedside estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from database.models import Granularity
from backend.sync import profile as profiling

#: A grouped split needs enough distinct people that each fold holds several. Below this
#: a cross-validated score says more about which subjects landed where than about a model.
MIN_SUBJECTS = 10
MIN_ROWS = 200

#: Scales that express a pain rating as a magnitude. A binary flag is excluded: the model
#: this platform trains is a regression onto 0-10, and a 0/1 column cannot supply that.
CONTINUOUS_SCALES = (profiling.NRS, profiling.VAS)


@dataclass
class Verdict:
    trainable: bool = False
    task: str = "pain_intensity_regression"
    reasons: list[str] = field(default_factory=list)
    met: list[str] = field(default_factory=list)
    target_column: str | None = None
    subject_column: str | None = None
    target_scale: str = profiling.UNKNOWN_SCALE

    #: Never true from here. A model fitted on an external table predicts that table's
    #: rating from that table's columns; it shares no feature schema with the clinical
    #: estimator and must not be offered for bedside use. Kept as a field so the interface
    #: states it rather than leaving a reader to assume either way.
    clinically_usable: bool = False

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "trainable": self.trainable,
            "clinically_usable": self.clinically_usable,
            "target_column": self.target_column,
            "subject_column": self.subject_column,
            "target_scale": self.target_scale,
            "conditions_met": self.met,
            "reasons": self.reasons,
            "note": (
                "A model trained from this dataset is a baseline for the dataset itself. "
                "It is recorded inactive and is not used for any clinical estimate."
            ),
        }


def assess(measured: profiling.Profile) -> Verdict:
    verdict = Verdict(
        target_column=measured.target_column,
        subject_column=measured.subject_column,
        target_scale=measured.target_scale,
    )

    if measured.file is None:
        verdict.reasons.append(
            "the dataset holds no tabular file, so no supervised target could be looked for"
        )
        return verdict

    if measured.granularity is Granularity.AGGREGATE:
        verdict.reasons.append(
            "rows describe places and periods rather than individual people, so the "
            "dataset carries no per-patient pain rating to learn from"
        )
    elif measured.granularity is Granularity.UNKNOWN:
        verdict.reasons.append(
            "no subject identifier was found and the columns do not identify the rows as "
            "aggregates either, so it could not be established what a row describes"
        )
    else:
        verdict.met.append("rows describe individual subjects")

    if not measured.target_column:
        verdict.reasons.append(
            "no column carrying a pain rating was found among "
            f"{len(measured.columns)} column(s)"
        )
    elif measured.target_scale == profiling.BINARY:
        verdict.reasons.append(
            f"the rating column {measured.target_column!r} holds a two-valued pain/no-pain "
            "flag; the platform's model estimates a 0-10 intensity and cannot be trained "
            "on a binary label"
        )
    elif measured.target_scale not in CONTINUOUS_SCALES:
        verdict.reasons.append(
            f"the values in {measured.target_column!r} do not sit on a recognised pain "
            "rating scale, so the column cannot be read as an intensity"
        )
    else:
        verdict.met.append(
            f"{measured.target_column!r} carries a pain rating on the "
            f"{measured.target_scale} scale"
        )

    if not measured.subject_column:
        verdict.reasons.append(
            "no subject identifier is present, so train and test splits cannot be "
            "separated by person and any score would be inflated by leakage"
        )
    elif measured.subjects is not None and measured.subjects < MIN_SUBJECTS:
        verdict.reasons.append(
            f"the table covers {measured.subjects} distinct subject(s); a grouped split "
            f"needs at least {MIN_SUBJECTS}"
        )
    else:
        verdict.met.append(
            f"subjects can be separated by {measured.subject_column!r}"
            + (f" across {measured.subjects} people" if measured.subjects else "")
        )

    if measured.rows is None or measured.rows < MIN_ROWS:
        verdict.reasons.append(
            f"the table holds {measured.rows or 0:,} row(s), below the {MIN_ROWS:,} needed "
            "for an evaluation to mean anything"
        )
    else:
        verdict.met.append(f"{measured.rows:,} rows")

    if not measured.numeric_columns or (
        measured.target_column
        and [c for c in measured.numeric_columns if c != measured.target_column] == []
    ):
        verdict.reasons.append(
            "the table carries no numeric column besides the rating itself, so there are "
            "no features to fit against"
        )
    elif measured.target_column:
        usable = [
            column
            for column in measured.numeric_columns
            if column not in (measured.target_column, measured.subject_column)
        ]
        verdict.met.append(f"{len(usable)} numeric feature column(s) available")

    verdict.trainable = not verdict.reasons
    if verdict.trainable:
        verdict.reasons.append(
            "every structural condition for a per-subject pain intensity baseline is met"
        )
    return verdict
