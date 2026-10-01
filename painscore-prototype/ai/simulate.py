from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT / "dataset" / "dataset.csv"

PATIENT_COUNT = 36
SEED = 20261001

SCENARIO_PLAN = (
    ("rest", 30),
    ("pain", 66),
    ("exercise", 18),
    ("anxiety", 18),
    ("sedated", 12),
    ("sensor_failure", 16),
)

STREAMS = ("A", "B", "C")

STREAM_NAMES = {
    "A": "neuro-muscular",
    "B": "smart patch",
    "C": "contextual AI",
}

STREAM_FEATURES = {
    "A": (
        "a_alpha_power",
        "a_beta_power",
        "a_theta_power",
        "a_theta_beta_ratio",
        "a_emg_amplitude_uv",
        "a_emg_delta_uv",
    ),
    "B": (
        "b_heart_rate",
        "b_hr_delta",
        "b_hrv_rmssd",
        "b_hrv_sdnn",
        "b_gsr_tonic_us",
        "b_gsr_delta_us",
        "b_gsr_phasic_peaks",
        "b_skin_temp_c",
        "b_temp_delta_c",
        "b_respiration_rate",
        "b_resp_delta",
        "b_motion_index",
        "b_pain_stress_index",
    ),
    "C": (
        "c_au4",
        "c_au6",
        "c_au7",
        "c_au9",
        "c_au10",
        "c_au43",
        "c_rppg_hr",
        "c_voice_f0",
        "c_voice_jitter",
        "c_voice_intensity",
        "c_voice_present",
    ),
}

QUALITY_COLUMNS = {"A": "a_quality", "B": "b_quality", "C": "c_quality"}

GATE_COLUMNS = ("c_smile_detected", "c_talk_detected", "c_lighting", "c_occluded")

THERAPY_COLUMNS = (
    "therapy_tens",
    "therapy_vibration",
    "therapy_thermotherapy",
    "therapy_photobiomodulation",
)

IDENTITY_COLUMNS = ("patient_id", "window_index", "scenario", "failed_stream", "clinical_context")

LABEL_COLUMN = "pain_label"
SELF_REPORT_COLUMN = "self_report_nrs"
CONFOUNDER_COLUMN = "confounder_class"

ALL_FEATURES = tuple(name for stream in STREAMS for name in STREAM_FEATURES[stream])

PAIN_FACE_UNITS = ("c_au4", "c_au6", "c_au7", "c_au9", "c_au10")


@dataclass(frozen=True)
class Patient:
    identifier: str
    context: str
    heart_rate: float
    hrv: float
    gsr: float
    skin_temp: float
    respiration: float
    emg_tone: float
    alpha: float
    beta: float
    theta: float
    autonomic_gain: float
    expressiveness: float
    guarding_gain: float
    emg_noise: float
    band_noise: float
    lability: float
    occlusion_rate: float
    report_bias: float


def saturate(value, span):
    return float(np.clip(value / span, 0.0, 1.0))


def face_access(rng):
    if rng.random() < 0.20:
        return float(rng.uniform(0.55, 0.90))
    return float(0.06 + abs(rng.normal(0.0, 0.04)))


def draw_patients(rng):
    patients = []
    for index in range(PATIENT_COUNT):
        patients.append(
            Patient(
                identifier=f"VP-{index + 1:02d}",
                context="conscious_er" if index % 3 == 0 else "conscious_ward",
                heart_rate=float(np.clip(rng.normal(68.0, 7.5), 52.0, 90.0)),
                hrv=float(np.clip(rng.normal(42.0, 11.0), 16.0, 78.0)),
                gsr=float(np.clip(rng.normal(4.6, 1.2), 1.6, 9.0)),
                skin_temp=float(np.clip(rng.normal(33.2, 0.6), 31.4, 35.0)),
                respiration=float(np.clip(rng.normal(14.0, 2.0), 10.0, 20.0)),
                emg_tone=float(np.clip(rng.normal(8.0, 1.9), 4.2, 13.5)),
                alpha=float(np.clip(rng.normal(12.0, 2.4), 6.0, 18.0)),
                beta=float(np.clip(rng.normal(6.0, 1.4), 3.0, 10.0)),
                theta=float(np.clip(rng.normal(9.0, 2.0), 4.5, 15.0)),
                autonomic_gain=float(rng.uniform(0.62, 1.38)),
                expressiveness=float(rng.uniform(0.20, 1.60)),
                guarding_gain=float(rng.uniform(0.55, 1.45)),
                emg_noise=float(rng.uniform(0.8, 2.2)),
                band_noise=float(rng.uniform(0.6, 2.2)),
                lability=float(rng.uniform(0.5, 1.8)),
                occlusion_rate=face_access(rng),
                report_bias=float(rng.normal(0.0, 0.9)),
            )
        )
    return patients


def electrode_contact(rng):
    if rng.random() < 0.06:
        return float(rng.uniform(0.05, 0.34))
    return float(np.clip(rng.normal(0.90, 0.07), 0.36, 0.99))


def neuromuscular(patient, pain, scenario, rng):
    intensity = pain / 10.0
    sedated = scenario == "sedated"
    contact = electrode_contact(rng)
    artefact = 1.0 + 6.0 * (1.0 - contact) ** 2
    drift = patient.band_noise * artefact
    alpha = patient.alpha * (1.0 - 0.32 * intensity + (0.55 if sedated else 0.0)) + rng.normal(0.0, drift)
    beta = patient.beta * (1.0 + 0.55 * intensity - (0.30 if sedated else 0.0)) + rng.normal(0.0, 0.6 * drift)
    theta = patient.theta * (1.0 + 0.18 * intensity + (0.48 if sedated else 0.0)) + rng.normal(0.0, 0.9 * drift)
    alpha = max(alpha, 0.6)
    beta = max(beta, 0.5)
    theta = max(theta, 0.6)
    guarding = patient.emg_tone * 1.20 * intensity * patient.guarding_gain
    if sedated:
        guarding *= 0.55
    emg = max(patient.emg_tone + guarding + rng.normal(0.0, patient.emg_noise * artefact), 0.6)
    return {
        "a_alpha_power": alpha,
        "a_beta_power": beta,
        "a_theta_power": theta,
        "a_theta_beta_ratio": theta / beta,
        "a_emg_amplitude_uv": emg,
        "a_emg_delta_uv": emg - patient.emg_tone,
        "a_quality": contact,
    }


def stress_index(patient, heart_rate, hrv, gsr, respiration):
    return 100.0 * (
        0.34 * saturate(heart_rate - patient.heart_rate, 42.0)
        + 0.30 * saturate(gsr - patient.gsr, 6.0)
        + 0.22 * saturate(1.0 - hrv / patient.hrv, 1.0)
        + 0.14 * saturate(respiration - patient.respiration, 12.0)
    )


def smart_patch(patient, pain, scenario, rng):
    intensity = pain / 10.0
    exertion = scenario == "exercise"
    worry = scenario == "anxiety"
    sedated = scenario == "sedated"

    arousal = float(rng.normal(0.0, 1.0)) * patient.lability

    if exertion:
        motion = float(rng.uniform(0.34, 0.97))
    elif worry:
        motion = float(rng.uniform(0.10, 0.46))
    elif sedated:
        motion = float(rng.uniform(0.01, 0.06))
    else:
        motion = float(np.clip(0.07 + 0.10 * intensity + abs(rng.normal(0.0, 0.13)), 0.0, 0.98))

    adhesion = float(rng.uniform(0.10, 0.40)) if rng.random() < 0.05 else 1.0
    artefact = 1.0 + 2.5 * motion + 5.0 * (1.0 - adhesion)

    heart_rate = (
        patient.heart_rate
        + 19.0 * intensity * patient.autonomic_gain
        + 7.5 * arousal
        + rng.normal(0.0, 2.4 * artefact)
    )
    hrv = patient.hrv * (1.0 - 0.40 * intensity - 0.10 * arousal)
    gsr = patient.gsr + 2.8 * intensity * patient.autonomic_gain + 0.9 * arousal + rng.normal(0.0, 0.42 * artefact)
    peaks = 1.2 + 6.0 * intensity + 1.4 * arousal + rng.normal(0.0, 0.9 * artefact)
    skin_temp = patient.skin_temp - 0.45 * intensity - 0.12 * arousal + rng.normal(0.0, 0.22 * artefact)
    respiration = patient.respiration + 4.2 * intensity + 1.3 * arousal + rng.normal(0.0, 0.9 * artefact)

    if exertion:
        heart_rate += 30.0
        hrv *= 0.55
        gsr += 2.2
        peaks += 2.4
        skin_temp += 0.85
        respiration += 7.5
    if worry:
        heart_rate += 14.0
        hrv *= 0.74
        gsr += 2.9
        peaks += 4.2
        skin_temp -= 0.38
        respiration += 3.0
    if sedated:
        heart_rate -= 5.0
        hrv *= 1.16
        gsr -= 0.8
        respiration -= 2.2

    hrv = max(hrv + rng.normal(0.0, 1.8 * artefact), 4.0)
    gsr = max(gsr, 0.4)
    respiration = max(respiration, 7.0)
    peaks = max(peaks, 0.0)

    quality = float(np.clip(rng.normal(0.94, 0.05), 0.3, 0.99)) * (1.0 - 0.30 * motion) * adhesion

    return {
        "b_heart_rate": heart_rate,
        "b_hr_delta": heart_rate - patient.heart_rate,
        "b_hrv_rmssd": hrv,
        "b_hrv_sdnn": hrv * float(rng.uniform(1.25, 1.65)),
        "b_gsr_tonic_us": gsr,
        "b_gsr_delta_us": gsr - patient.gsr,
        "b_gsr_phasic_peaks": peaks,
        "b_skin_temp_c": skin_temp,
        "b_temp_delta_c": skin_temp - patient.skin_temp,
        "b_respiration_rate": respiration,
        "b_resp_delta": respiration - patient.respiration,
        "b_motion_index": motion,
        "b_pain_stress_index": stress_index(patient, heart_rate, hrv, gsr, respiration),
        "b_quality": float(quality),
    }


def contextual(patient, pain, scenario, rng, motion, heart_rate):
    intensity = pain / 10.0
    sedated = scenario == "sedated"
    expressive = patient.expressiveness * (0.15 if sedated else 1.0)

    lighting = float(np.clip(rng.normal(0.82, 0.17), 0.15, 1.0))
    occluded = 1.0 if rng.random() < patient.occlusion_rate else 0.0
    clarity = lighting * (0.18 if occluded else 1.0) * (1.0 - 0.32 * motion)
    blur = 0.45 * (1.0 + 4.0 * (1.0 - clarity))

    units = {
        "c_au4": 0.35 + 3.40 * intensity * expressive,
        "c_au6": 0.25 + 2.60 * intensity * expressive,
        "c_au7": 0.30 + 3.00 * intensity * expressive,
        "c_au9": 0.15 + 2.30 * intensity * expressive,
        "c_au10": 0.15 + 2.10 * intensity * expressive,
    }
    closed_eyes = 4.3 + rng.normal(0.0, 0.3) if sedated else 0.25 + 1.5 * intensity * patient.expressiveness

    smiling = not sedated and rng.random() < 0.10
    talking = not sedated and rng.random() < 0.15
    if smiling:
        units["c_au6"] += 2.6
        units["c_au10"] += 1.5
    if talking:
        units["c_au10"] += 0.9

    window = {name: float(np.clip(value + rng.normal(0.0, blur), 0.0, 5.0)) for name, value in units.items()}
    window["c_au43"] = float(np.clip(closed_eyes + rng.normal(0.0, 0.30 + 0.5 * blur), 0.0, 5.0))

    speaking = talking or (not sedated and rng.random() < 0.45)

    window["c_rppg_hr"] = 0.0 if occluded else heart_rate + rng.normal(0.0, 2.4 + 9.0 * motion)
    window["c_voice_f0"] = 148.0 + 38.0 * intensity + rng.normal(0.0, 7.0) if speaking else 0.0
    window["c_voice_jitter"] = 0.9 + 1.5 * intensity + rng.normal(0.0, 0.18) if speaking else 0.0
    window["c_voice_intensity"] = 58.0 + 9.0 * intensity + rng.normal(0.0, 2.5) if speaking else 0.0
    window["c_voice_present"] = 1.0 if speaking else 0.0
    window["c_smile_detected"] = 1.0 if smiling else 0.0
    window["c_talk_detected"] = 1.0 if talking else 0.0
    window["c_lighting"] = lighting
    window["c_occluded"] = occluded
    window["c_quality"] = float(np.clip(clarity * rng.normal(0.96, 0.03), 0.02, 0.99))
    return window


def failing_streams(rng):
    draw = rng.random()
    if draw < 0.55:
        return (str(rng.choice(STREAMS)),)
    if draw < 0.85:
        return tuple(sorted(rng.choice(STREAMS, size=2, replace=False)))
    return STREAMS


def fail_stream(window, stream, rng):
    if stream == "A":
        window["a_alpha_power"] = float(rng.uniform(0.1, 0.5))
        window["a_beta_power"] = float(rng.uniform(0.1, 0.5))
        window["a_theta_power"] = float(rng.uniform(0.1, 0.5))
        window["a_theta_beta_ratio"] = window["a_theta_power"] / window["a_beta_power"]
        window["a_emg_amplitude_uv"] = float(rng.uniform(0.1, 0.6))
        window["a_emg_delta_uv"] = 0.0
        window["a_quality"] = float(rng.uniform(0.02, 0.17))
    if stream == "B":
        window["b_heart_rate"] = 0.0
        window["b_hr_delta"] = 0.0
        window["b_hrv_rmssd"] = 0.0
        window["b_hrv_sdnn"] = 0.0
        window["b_gsr_tonic_us"] = float(rng.uniform(0.0, 0.2))
        window["b_gsr_delta_us"] = 0.0
        window["b_gsr_phasic_peaks"] = 0.0
        window["b_skin_temp_c"] = float(rng.uniform(23.5, 26.5))
        window["b_temp_delta_c"] = 0.0
        window["b_respiration_rate"] = 0.0
        window["b_resp_delta"] = 0.0
        window["b_pain_stress_index"] = 0.0
        window["b_quality"] = float(rng.uniform(0.02, 0.15))
    if stream == "C":
        for name in PAIN_FACE_UNITS:
            window[name] = 0.0
        window["c_au43"] = 0.0
        window["c_rppg_hr"] = 0.0
        window["c_voice_f0"] = 0.0
        window["c_voice_jitter"] = 0.0
        window["c_voice_intensity"] = 0.0
        window["c_voice_present"] = 0.0
        window["c_smile_detected"] = 0.0
        window["c_talk_detected"] = 0.0
        window["c_lighting"] = float(rng.uniform(0.02, 0.15))
        window["c_occluded"] = 1.0
        window["c_quality"] = float(rng.uniform(0.02, 0.12))
    return window


def confounder_class(scenario, pain):
    if scenario in ("exercise", "anxiety", "rest"):
        return scenario
    return "pain" if pain > 0 else "rest"


def self_report(patient, pain, scenario, rng):
    if scenario == "sedated":
        return None
    reported = pain + patient.report_bias + rng.normal(0.0, 0.9)
    return int(np.clip(round(reported), 0, 10))


def therapy_flags(pain, rng):
    engaged = pain >= 5 and rng.random() < 0.55
    return {
        "therapy_tens": 1 if engaged and rng.random() < 0.7 else 0,
        "therapy_vibration": 1 if engaged and rng.random() < 0.4 else 0,
        "therapy_thermotherapy": 1 if engaged and rng.random() < 0.5 else 0,
        "therapy_photobiomodulation": 1 if engaged and rng.random() < 0.3 else 0,
    }


def scenario_schedule(rng):
    schedule = []
    for scenario, count in SCENARIO_PLAN:
        schedule.extend([scenario] * count)
    rng.shuffle(schedule)
    return schedule


def build_window(patient, window_index, scenario, rng):
    failed = ""
    if scenario == "sedated":
        pain = int(rng.integers(3, 10))
        context = "unconscious_sedated"
    elif scenario == "pain":
        pain = int(rng.integers(1, 11))
        context = patient.context
    elif scenario == "sensor_failure":
        scenario = str(rng.choice(["rest", "pain", "exercise", "anxiety"]))
        pain = int(rng.integers(1, 11)) if scenario == "pain" else 0
        context = patient.context
        failed = "+".join(failing_streams(rng))
    else:
        pain = 0
        context = patient.context

    window = {
        "patient_id": patient.identifier,
        "window_index": window_index,
        "scenario": scenario,
        "failed_stream": failed,
        "clinical_context": context,
        LABEL_COLUMN: pain,
        SELF_REPORT_COLUMN: self_report(patient, pain, scenario, rng),
        CONFOUNDER_COLUMN: confounder_class(scenario, pain),
    }
    window.update(neuromuscular(patient, pain, scenario, rng))
    patch = smart_patch(patient, pain, scenario, rng)
    window.update(patch)
    window.update(
        contextual(patient, pain, scenario, rng, patch["b_motion_index"], patch["b_heart_rate"])
    )
    window.update(therapy_flags(pain, rng))
    for stream in failed.split("+") if failed else ():
        fail_stream(window, stream, rng)
    return window


def generate(seed=SEED):
    rng = np.random.default_rng(seed)
    patients = draw_patients(rng)
    rows = []
    for patient in patients:
        for window_index, scenario in enumerate(scenario_schedule(rng)):
            rows.append(build_window(patient, window_index, scenario, rng))
    columns = (
        list(IDENTITY_COLUMNS)
        + [LABEL_COLUMN, SELF_REPORT_COLUMN, CONFOUNDER_COLUMN]
        + list(ALL_FEATURES)
        + [QUALITY_COLUMNS[stream] for stream in STREAMS]
        + list(GATE_COLUMNS)
        + list(THERAPY_COLUMNS)
    )
    return pd.DataFrame(rows)[columns]


def main():
    frame = generate()
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(DATASET_PATH, index=False, float_format="%.4f")
    print(f"{len(frame)} windows from {frame['patient_id'].nunique()} virtual patients")
    print(frame["scenario"].value_counts().to_string())
    print(f"written to {DATASET_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
