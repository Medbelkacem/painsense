from dataclasses import dataclass

AGGRAVATING = "AGGRAVATING"
RELIEVING = "RELIEVING"


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    kind: str


FACTORS = (
    Factor("MOVEMENT", "Movement", AGGRAVATING),
    Factor("WALKING", "Walking", AGGRAVATING),
    Factor("EXERCISE", "Exertion", AGGRAVATING),
    Factor("BREATHING", "Deep breathing", AGGRAVATING),
    Factor("COUGHING", "Coughing", AGGRAVATING),
    Factor("EATING", "Eating", AGGRAVATING),
    Factor("POSITION_AGG", "A particular position", AGGRAVATING),
    Factor("TOUCH", "Light touch", AGGRAVATING),
    Factor("PRESSURE_AGG", "Pressure on the site", AGGRAVATING),
    Factor("NIGHT", "Night-time", AGGRAVATING),
    Factor("STRESS", "Stress", AGGRAVATING),
    Factor("COLD_EXPOSURE", "Cold exposure", AGGRAVATING),
    Factor("OTHER_AGGRAVATING", "Other", AGGRAVATING),
    Factor("REST", "Rest", RELIEVING),
    Factor("POSITION_REL", "Change of position", RELIEVING),
    Factor("MEDICATION", "Medication", RELIEVING),
    Factor("HEAT", "Heat", RELIEVING),
    Factor("COLD", "Cold", RELIEVING),
    Factor("MOVEMENT_REL", "Gentle movement", RELIEVING),
    Factor("FOOD", "Eating or antacids", RELIEVING),
    Factor("OTHER_RELIEVING", "Other", RELIEVING),
)

BY_CODE = {factor.code: factor for factor in FACTORS}


def of_kind(kind: str) -> tuple[Factor, ...]:
    return tuple(factor for factor in FACTORS if factor.kind == kind)
