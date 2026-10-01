from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

from knowledge.context import FUNCTIONAL_DOMAINS

if TYPE_CHECKING:
    from dataset.synthetic.generate import Draft


STANDARD = "STANDARD"

Hook = Callable[[np.random.Generator, "Draft"], None]


@dataclass(frozen=True)
class Scenario:
    code: str
    version: str
    description: str
    weight: float
    prepare: Hook | None = None
    finish: Hook | None = None


def _uniform(rng: np.random.Generator, low: float, high: float) -> float:
    return float(rng.uniform(low, high))


def _chance(rng: np.random.Generator, probability: float) -> bool:
    return bool(rng.random() < probability)


A_HIGH_HR_LOW_PAIN = "A_HIGH_HR_LOW_PAIN"
A_VERSION = "1"


def _a_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 0.0, 2.0)
    state = "recent_activity" if _chance(rng, 0.4) else "anxiety"
    draft.truth[state] = True

    if _chance(rng, 0.7):
        draft.confounders.add("RECENT_ACTIVITY" if state == "recent_activity" else "ANXIETY")


def _a_finish(rng: np.random.Generator, draft: Draft) -> None:
    if "hr" in draft.vitals:
        draft.vitals["hr"] = max(draft.vitals["hr"], round(_uniform(rng, 104.0, 132.0)))


B_SEVERE_PAIN_NORMAL_VITALS = "B_SEVERE_PAIN_NORMAL_VITALS"
B_VERSION = "1"


def _b_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 7.0, 9.5)


def _b_finish(rng: np.random.Generator, draft: Draft) -> None:
    resting = draft.resting_vitals()
    for name in ("hr", "resp_rate", "sbp", "dbp"):
        if name in draft.vitals:
            draft.vitals[name] = resting[name]


C_CHRONIC_SEVERE_STABLE = "C_CHRONIC_SEVERE_STABLE"
C_VERSION = "1"


def _c_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 7.0, 9.0)
    draft.duration_hours = round(_uniform(rng, 4400.0, 40000.0), 1)
    draft.onset_speed = "WEEKS_OR_MORE"
    draft.onset = "GRADUAL"
    draft.pattern = "CONSTANT"
    draft.course = "STABLE"
    draft.episodes_per_day = None
    draft.episode_minutes = None


def _c_finish(rng: np.random.Generator, draft: Draft) -> None:
    resting = draft.resting_vitals()
    for name in ("hr", "resp_rate", "sbp", "dbp"):
        if name in draft.vitals:
            draft.vitals[name] = resting[name]


D_EXERCISE_HIGH_HR = "D_EXERCISE_HIGH_HR"
D_VERSION = "1"


def _d_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 0.5, 2.5)
    draft.truth["recent_activity"] = True
    draft.factors.add("EXERCISE")
    draft.timing.add("AFTER_ACTIVITY")
    if _chance(rng, 0.8):
        draft.confounders.add("RECENT_ACTIVITY")


def _d_finish(rng: np.random.Generator, draft: Draft) -> None:
    if "hr" in draft.vitals:
        draft.vitals["hr"] = max(draft.vitals["hr"], round(_uniform(rng, 100.0, 128.0)))
    if "resp_rate" in draft.vitals:
        draft.vitals["resp_rate"] = min(draft.vitals["resp_rate"] + 3.0, 40.0)


E_MEDICATION_BLUNTING = "E_MEDICATION_BLUNTING"
E_VERSION = "1"


def _e_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 7.0, 9.0)
    which = rng.random()
    if which < 0.7:
        draft.add_medication(
            "OPIOID",
            dose_category="HIGH" if _chance(rng, 0.4) else "STANDARD",
            frequency="FOUR_TIMES_DAILY" if _chance(rng, 0.6) else "CONTINUOUS",
            hours_since_last_dose=round(_uniform(rng, 0.5, 4.0), 1),
            pain_effect="PARTIAL" if _chance(rng, 0.4) else "NONE",
            sedation_effect="MILD" if _chance(rng, 0.5) else "NONE",
        )
    if which >= 0.4:
        draft.add_medication(
            "ANTIHYPERTENSIVE",
            dose_category="STANDARD",
            frequency="DAILY",
            hours_since_last_dose=round(_uniform(rng, 1.0, 20.0), 1),
        )
        draft.truth["beta_blocker"] = True
        if _chance(rng, 0.75):
            draft.confounders.add("BETA_BLOCKER")


F_MULTI_SITE = "F_MULTI_SITE"
F_VERSION = "1"


def _f_finish(rng: np.random.Generator, draft: Draft) -> None:
    draft.localised = True
    wanted = int(rng.integers(3, 6))
    roles = ("SECONDARY", "REFERRED", "RADIATING")
    guard = 0
    while len(draft.sites) < wanted and guard < 12:
        guard += 1
        candidates = draft.candidate_site_codes()
        if not candidates:
            break
        code = candidates[int(rng.integers(len(candidates)))]
        role = roles[int(rng.integers(len(roles)))]
        origin = draft.sites[0] if role in ("RADIATING", "REFERRED") else None
        draft.add_site(code, role, origin=origin)
    if any(site.role == "RADIATING" for site in draft.sites):
        draft.radiates = True


G_INCOMPLETE = "G_INCOMPLETE"
G_VERSION = "1"


def _keep_some(rng: np.random.Generator, mapping: dict, at_most: int) -> dict:
    keys = list(mapping)
    keep = int(rng.integers(0, at_most + 1))
    chosen = set(rng.choice(keys, size=min(keep, len(keys)), replace=False)) if keys else set()
    return {key: mapping[key] for key in keys if key in chosen}


def _g_finish(rng: np.random.Generator, draft: Draft) -> None:
    draft.vitals = _keep_some(rng, draft.vitals, 2)
    draft.answers = _keep_some(rng, draft.answers, 2)
    draft.functional_impact = _keep_some(rng, draft.functional_impact, 2)
    if _chance(rng, 0.5):
        draft.symptoms.clear()
    if _chance(rng, 0.4):
        draft.duration_hours = None
    if _chance(rng, 0.4):
        draft.onset = "UNKNOWN"
        draft.onset_speed = "UNKNOWN"
    if _chance(rng, 0.4):
        draft.pattern = "UNKNOWN"
        draft.episodes_per_day = None
        draft.episode_minutes = None
    if _chance(rng, 0.4):
        draft.course = "UNKNOWN"
    if _chance(rng, 0.5):
        draft.radiates = None
    if _chance(rng, 0.5):
        draft.factors.clear()
    if _chance(rng, 0.5):
        draft.medications.clear()
    if _chance(rng, 0.5):
        draft.localised = False
    if _chance(rng, 0.3):
        draft.qualities.clear()
    if _chance(rng, 0.15):
        draft.age = None


H_CONFLICTING = "H_CONFLICTING"
H_VERSION = "1"


def _conflict_constant_with_episodes(rng, draft: Draft) -> None:
    draft.pattern = "CONSTANT"
    draft.episodes_per_day = round(_uniform(rng, 1.0, 6.0), 1)


def _conflict_radiation_denied(rng, draft: Draft) -> None:
    draft.localised = True
    if not any(site.role == "RADIATING" for site in draft.sites):
        candidates = draft.candidate_site_codes()
        if candidates:
            code = candidates[int(rng.integers(len(candidates)))]
            draft.add_site(code, "RADIATING", origin=draft.sites[0])
    draft.radiates = False


def _conflict_onset(rng, draft: Draft) -> None:
    draft.onset = "GRADUAL"
    draft.onset_speed = "SECONDS"


def _conflict_first_episode_recurrent(rng, draft: Draft) -> None:
    draft.answers["FIRST_EPISODE"] = True
    draft.recurrent = True


def _conflict_first_episode_compared(rng, draft: Draft) -> None:
    draft.answers["FIRST_EPISODE"] = True
    draft.answers["SIMILAR_PAST_PAIN"] = bool(rng.random() < 0.5)


def _conflict_rest_and_movement(rng, draft: Draft) -> None:
    draft.factors.update({"REST", "MOVEMENT_REL"})


def _conflict_pressures(rng, draft: Draft) -> None:
    if "sbp" in draft.vitals:
        draft.vitals["dbp"] = draft.vitals["sbp"] + round(_uniform(rng, 2.0, 15.0))


def _conflict_no_primary(rng, draft: Draft) -> None:
    draft.localised = True
    draft.sites = [
        replace(site, role="SECONDARY") if site.role == "PRIMARY" else site
        for site in draft.sites
    ]


CONFLICTS: tuple[Hook, ...] = (
    _conflict_constant_with_episodes,
    _conflict_radiation_denied,
    _conflict_onset,
    _conflict_first_episode_recurrent,
    _conflict_first_episode_compared,
    _conflict_rest_and_movement,
    _conflict_pressures,
    _conflict_no_primary,
)


def _h_finish(rng: np.random.Generator, draft: Draft) -> None:
    count = int(rng.integers(1, 4))
    for index in rng.choice(len(CONFLICTS), size=count, replace=False):
        CONFLICTS[int(index)](rng, draft)


NO_PAIN = "NO_PAIN"
NO_PAIN_VERSION = "1"


def _no_pain_prepare(rng: np.random.Generator, draft: Draft) -> None:
    draft.latent = _uniform(rng, 0.0, 1.0)
    if _chance(rng, 0.7):
        draft.symptoms.clear()
    draft.course = "IMPROVING" if _chance(rng, 0.6) else "STABLE"
    draft.medications = [
        entry
        for entry in draft.medications
        if not draft.is_analgesic(entry) or _chance(rng, 0.2)
    ]


def _no_pain_finish(rng: np.random.Generator, draft: Draft) -> None:
    for domain in FUNCTIONAL_DOMAINS:
        if domain in draft.functional_impact:
            draft.functional_impact[domain] = 1 if _chance(rng, 0.1) else 0


I_FEVER_NO_PAIN = "I_FEVER_NO_PAIN"
I_VERSION = "1"


def _i_prepare(rng: np.random.Generator, draft: Draft) -> None:
    """A febrile patient who is not in pain. The fever alone lifts heart rate and
    respiratory rate, which is the commonest way to read pain into a reading that has
    none."""
    draft.latent = _uniform(rng, 0.0, 1.5)
    draft.truth["febrile"] = True
    draft.symptoms.add("FEVER")
    if _chance(rng, 0.8):
        draft.confounders.add("FEVER_CONTEXT")


def _i_finish(rng: np.random.Generator, draft: Draft) -> None:
    if "temperature_c" in draft.vitals:
        draft.vitals["temperature_c"] = max(
            draft.vitals["temperature_c"], round(_uniform(rng, 38.3, 40.0), 1)
        )
    for domain in FUNCTIONAL_DOMAINS:
        if domain in draft.functional_impact:
            draft.functional_impact[domain] = min(draft.functional_impact[domain], 1)


J_DISTRESS_NO_PAIN = "J_DISTRESS_NO_PAIN"
J_VERSION = "1"


def _j_prepare(rng: np.random.Generator, draft: Draft) -> None:
    """A young child or newborn who is distressed rather than in pain: hungry, tired,
    freshly handled or separated from a parent. Indistinguishable from pain on vital signs
    alone, which is exactly why the observational scale is the reference."""
    draft.latent = _uniform(rng, 0.0, 1.5)
    state = str(rng.choice(["hunger", "fatigue", "handling", "separation_distress"]))
    draft.truth[state] = True
    recorded = {
        "hunger": "HUNGER",
        "fatigue": "FATIGUE",
        "handling": "HANDLING",
        "separation_distress": "SEPARATION_DISTRESS",
    }[state]
    if _chance(rng, 0.75):
        draft.confounders.add(recorded)


def _j_finish(rng: np.random.Generator, draft: Draft) -> None:
    for domain in FUNCTIONAL_DOMAINS:
        if domain in draft.functional_impact:
            draft.functional_impact[domain] = 1 if _chance(rng, 0.2) else 0


K_SEDATED_HIGH_PAIN = "K_SEDATED_HIGH_PAIN"
K_VERSION = "1"


def _k_prepare(rng: np.random.Generator, draft: Draft) -> None:
    """Pain held high while sedation flattens every signal that would show it. The false
    negative that matters most: under-treating a patient who cannot say anything."""
    draft.latent = _uniform(rng, 6.0, 9.5)
    draft.truth["sedated"] = True
    if _chance(rng, 0.85):
        draft.confounders.add("SEDATION")


SCENARIOS = (
    Scenario(
        A_HIGH_HR_LOW_PAIN,
        A_VERSION,
        "Heart rate raised by anxiety or recent exertion, with little or no pain.",
        1.0,
        prepare=_a_prepare,
        finish=_a_finish,
    ),
    Scenario(
        B_SEVERE_PAIN_NORMAL_VITALS,
        B_VERSION,
        "Severe pain with the patient's own resting vital signs.",
        1.0,
        prepare=_b_prepare,
        finish=_b_finish,
    ),
    Scenario(
        C_CHRONIC_SEVERE_STABLE,
        C_VERSION,
        "Chronic severe pain of months to years with settled physiology.",
        1.0,
        prepare=_c_prepare,
        finish=_c_finish,
    ),
    Scenario(
        D_EXERCISE_HIGH_HR,
        D_VERSION,
        "Exertion in the last quarter hour, raised heart rate, low pain.",
        1.0,
        prepare=_d_prepare,
        finish=_d_finish,
    ),
    Scenario(
        E_MEDICATION_BLUNTING,
        E_VERSION,
        "Opioid or beta blockade holding the vital signs down while the pain stays high.",
        1.0,
        prepare=_e_prepare,
    ),
    Scenario(
        F_MULTI_SITE,
        F_VERSION,
        "Three to five painful sites with primary, secondary, radiating and referred roles.",
        1.0,
        finish=_f_finish,
    ),
    Scenario(
        G_INCOMPLETE,
        G_VERSION,
        "Most vital signs, answers and functional domains missing, sometimes below the "
        "threshold at which the estimate is withheld.",
        1.2,
        finish=_g_finish,
    ),
    Scenario(
        H_CONFLICTING,
        H_VERSION,
        "One to three recorded facts that cannot all be true, for the consistency checker.",
        1.0,
        finish=_h_finish,
    ),
    Scenario(
        NO_PAIN,
        NO_PAIN_VERSION,
        "An incidental visit with a latent intensity near zero.",
        1.3,
        prepare=_no_pain_prepare,
        finish=_no_pain_finish,
    ),
    Scenario(
        I_FEVER_NO_PAIN,
        I_VERSION,
        "Fever lifting the heart and respiratory rates with no pain behind it.",
        1.0,
        prepare=_i_prepare,
        finish=_i_finish,
    ),
    Scenario(
        J_DISTRESS_NO_PAIN,
        J_VERSION,
        "A newborn or young child distressed by hunger, tiredness, handling or "
        "separation rather than by pain.",
        1.0,
        prepare=_j_prepare,
        finish=_j_finish,
    ),
    Scenario(
        K_SEDATED_HIGH_PAIN,
        K_VERSION,
        "High pain with sedation flattening every signal that would show it.",
        1.0,
        prepare=_k_prepare,
    ),
)

BY_CODE = {scenario.code: scenario for scenario in SCENARIOS}
VERSIONS = {scenario.code: scenario.version for scenario in SCENARIOS}
