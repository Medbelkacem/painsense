from dataclasses import dataclass


@dataclass(frozen=True)
class Confounder:
    code: str
    label: str
    affects: tuple[str, ...]
    note: str


CONFOUNDERS = (
    Confounder(
        "ANXIETY",
        "Anxiety",
        ("hr", "resp_rate", "sbp"),
        "Raises heart rate, respiratory rate and blood pressure independently of pain.",
    ),
    Confounder(
        "FEAR",
        "Fear or distress about the examination",
        ("hr", "sbp"),
        "A sympathetic response to the setting rather than to the pain.",
    ),
    Confounder(
        "RECENT_ACTIVITY",
        "Physical activity in the last 15 minutes",
        ("hr", "resp_rate"),
        "Heart rate stays elevated for several minutes after exertion.",
    ),
    Confounder(
        "FEVER_CONTEXT",
        "Febrile",
        ("hr", "resp_rate"),
        "Each degree of fever adds roughly 10 beats per minute.",
    ),
    Confounder(
        "BETA_BLOCKER",
        "Taking a beta blocker",
        ("hr",),
        "Blunts the tachycardia that pain would otherwise produce.",
    ),
    Confounder(
        "ANALGESIA_RECENT",
        "Analgesia in the last 4 hours",
        ("hr", "resp_rate"),
        "Reported intensity and vitals both reflect the treatment, not the untreated pain.",
    ),
    Confounder(
        "OPIOID_THERAPY",
        "On regular opioid therapy",
        ("resp_rate", "hr"),
        "Lowers respiratory rate; tolerance also changes how intensity is reported.",
    ),
    Confounder(
        "SLEEP_DEPRIVATION",
        "Sleep deprivation",
        ("hr",),
        "Lowers pain threshold and raises resting heart rate.",
    ),
    Confounder(
        "CAFFEINE_STIMULANT",
        "Recent caffeine or stimulant",
        ("hr", "sbp"),
        "Raises heart rate and blood pressure independently of pain.",
    ),
    Confounder(
        "COMMUNICATION_BARRIER",
        "Communication barrier",
        (),
        "Self-report may understate or overstate intensity; it is still recorded as given.",
    ),
    Confounder(
        "STRESS",
        "Stress unrelated to the pain",
        ("hr", "resp_rate", "sbp"),
        "Activates the sympathetic system the way acute pain does.",
    ),
    Confounder(
        "SEDATION",
        "Sedated",
        ("hr", "resp_rate", "sbp"),
        "Flattens the autonomic response, so the signals understate the pain.",
    ),
    Confounder(
        "HUNGER",
        "Hungry or due a feed",
        ("hr", "resp_rate"),
        "In an infant, produces the same crying and autonomic picture as pain.",
    ),
    Confounder(
        "FATIGUE",
        "Tired or short of sleep",
        ("hr",),
        "Shifts the resting baseline and lowers the pain threshold.",
    ),
    Confounder(
        "HANDLING",
        "Recently handled or examined",
        ("hr", "resp_rate", "spo2"),
        "Handling alone raises a newborn's heart rate and unsettles the breathing.",
    ),
    Confounder(
        "SEPARATION_DISTRESS",
        "Distress at being separated from a parent",
        ("hr", "resp_rate"),
        "Distress rather than pain, and indistinguishable from it on vital signs alone.",
    ),
)

BY_CODE = {confounder.code: confounder for confounder in CONFOUNDERS}


def affecting(vital: str) -> tuple[str, ...]:
    return tuple(c.code for c in CONFOUNDERS if vital in c.affects)
