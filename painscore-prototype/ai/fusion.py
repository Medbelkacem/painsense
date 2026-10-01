import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.simulate import (
    PAIN_FACE_UNITS,
    QUALITY_COLUMNS,
    STREAMS,
    STREAM_NAMES,
)

CONFIG_PATH = ROOT / "config" / "weights.json"
LEARNED_PATH = ROOT / "config" / "learned_weights.json"
ARTIFACT_PATH = ROOT / "ai" / "trained.joblib"

LAYERS = ("base", "statistical", "ml", "attenuation")
DEFAULT_CONTEXT = "conscious_ward"
SEDATED_CONTEXT = "unconscious_sedated"
INSUFFICIENT = "INSUFFICIENT SIGNAL"

SIGNAL_LABELS = {
    "A": "EMG guarding and cortical shift",
    "B": "autonomic stress response",
    "C": "facial expression and rPPG",
}


def normalise(weights):
    total = sum(weights.values())
    if total <= 0.0:
        return {stream: 1.0 / len(STREAMS) for stream in STREAMS}
    return {stream: value / total for stream, value in weights.items()}


def listing(items):
    if len(items) < 2:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def clamp(value, low=0.0, high=1.0):
    return float(min(max(value, low), high))


def pain_face_intensity(window):
    return float(np.mean([window[name] for name in PAIN_FACE_UNITS]))


def heuristic_scores(window):
    bands = window["a_alpha_power"] + window["a_beta_power"] + window["a_theta_power"]
    beta_share = window["a_beta_power"] / bands if bands > 0 else 0.0
    cortical = clamp((beta_share - 0.20) / 0.18) * 10.0
    guarding = clamp(window["a_emg_delta_uv"] / 14.0) * 10.0
    return {
        "A": clamp(0.6 * guarding + 0.4 * cortical, 0.0, 10.0),
        "B": clamp(window["b_pain_stress_index"] / 10.0, 0.0, 10.0),
        "C": clamp(2.0 * pain_face_intensity(window), 0.0, 10.0),
    }


class Fusion:
    def __init__(self, config, learned=None, artifact=None):
        self.config = config
        self.contexts = config["clinical_contexts"]
        self.mix = config["layer_mix"]
        self.rules = config["attenuation"]
        self.patterns = config["confounder_rules"]
        self.confidence_mix = config["confidence_mix"]
        self.bands = config["contribution_bands"]
        self.agreement_span = config["score_scale"]["agreement_span"]
        uniform = {stream: 1.0 / len(STREAMS) for stream in STREAMS}
        self.statistical = normalise(learned["statistical"]) if learned else uniform
        self.ml = normalise(learned["ml"]) if learned else uniform
        self.artifact = artifact

    def base_weights(self, context):
        return normalise(self.contexts.get(context, self.contexts[DEFAULT_CONTEXT]))

    def composite_weights(self, context, layers=LAYERS):
        sources = {
            "base": self.base_weights(context),
            "statistical": self.statistical,
            "ml": self.ml,
        }
        ratios = {name: self.mix[name] if name in layers else 0.0 for name in sources}
        total = sum(ratios.values())
        if total <= 0.0:
            return {stream: 1.0 / len(STREAMS) for stream in STREAMS}
        blended = {
            stream: sum(ratios[name] * sources[name][stream] for name in sources) / total
            for stream in STREAMS
        }
        return normalise(blended)

    def confounder_factors(self, window, quality, verdict):
        factor = {stream: 1.0 for stream in STREAMS}
        reasons = {stream: [] for stream in STREAMS}

        if verdict in ("exercise", "anxiety"):
            factor["B"] = self.rules["autonomic_confound_factor"]
            reasons["B"].append(f"autonomic rise attributed to {verdict}")
        if window["b_motion_index"] >= self.rules["motion_threshold"]:
            factor["B"] = min(factor["B"], self.rules["motion_factor"])
            reasons["B"].append("high body motion")
        if quality["A"] <= self.rules["eeg_quality_threshold"]:
            factor["A"] = self.rules["eeg_failure_factor"]
            reasons["A"].append("poor EEG quality")
        if window["c_smile_detected"] or window["c_talk_detected"]:
            factor["C"] = self.rules["expression_factor"]
            reasons["C"].append("smiling or talking")
        if window["c_occluded"]:
            factor["C"] = min(factor["C"], self.rules["occlusion_factor"])
            reasons["C"].append("face occluded")
        if window["c_lighting"] <= self.rules["lighting_threshold"]:
            factor["C"] *= clamp(window["c_lighting"] / self.rules["lighting_threshold"])
            reasons["C"].append("poor lighting")

        return factor, reasons

    def stream_scores(self, window):
        if not self.artifact:
            return heuristic_scores(window)
        scores = {}
        for stream in STREAMS:
            columns = self.artifact["features"][stream]
            row = np.array([[float(window[name]) for name in columns]])
            scores[stream] = clamp(float(self.artifact["scorers"][stream].predict(row)[0]), 0.0, 10.0)
        return scores

    def confidence(self, scores, quality, final, composite):
        live = [stream for stream in STREAMS if final[stream] > 0.0]
        if not live:
            return 0.0
        quality_term = float(np.mean([quality[stream] for stream in live]))
        remaining = sum(final.values()) / max(sum(composite.values()), 1e-9)
        spread = float(np.std([scores[stream] for stream in live])) if len(live) > 1 else 0.0
        agreement = clamp(1.0 - spread / self.agreement_span)
        mix = self.confidence_mix
        blended = (
            mix["quality"] * quality_term
            + mix["remaining_weight"] * clamp(remaining)
            + mix["agreement"] * agreement
        )
        return round(100.0 * clamp(blended), 1)

    def contributions(self, final):
        total = sum(final.values())
        ranked = []
        for stream in STREAMS:
            share = final[stream] / total if total > 0 else 0.0
            if share >= self.bands["high"]:
                label = "HIGH"
            elif share >= self.bands["moderate"]:
                label = "MODERATE"
            else:
                label = "LOW"
            ranked.append(
                {
                    "stream": stream,
                    "name": STREAM_NAMES[stream],
                    "signal": SIGNAL_LABELS[stream],
                    "share": round(share, 4),
                    "label": label,
                }
            )
        return sorted(ranked, key=lambda entry: entry["share"], reverse=True)

    def observations(self, window):
        return {
            "heart_rate_up": window["b_hr_delta"] >= self.patterns["heart_rate_rise"],
            "gsr_up": window["b_gsr_delta_us"] >= self.patterns["gsr_rise"],
            "respiration_up": window["b_resp_delta"] >= self.patterns["respiration_rise"],
            "moving": window["b_motion_index"] >= self.patterns["motion_active"],
            "guarding": window["a_emg_delta_uv"] >= self.patterns["emg_rise"],
            "pain_face": pain_face_intensity(window) >= self.patterns["pain_face_intensity"],
        }

    def rule_verdict(self, window, quality, context):
        seen = self.observations(window)
        readable = self.rules["readable_quality"]
        if quality["A"] <= readable:
            seen["guarding"] = False
        if quality["C"] <= readable:
            seen["pain_face"] = False
        if quality["B"] <= readable:
            seen["heart_rate_up"] = False
            seen["gsr_up"] = False
            seen["respiration_up"] = False
        guarding = seen["guarding"]
        pain_face = seen["pain_face"]

        if guarding or pain_face:
            return "pain", seen
        if context == SEDATED_CONTEXT:
            return "sedated", seen
        if seen["moving"] and seen["respiration_up"]:
            return "exercise", seen
        if seen["heart_rate_up"] and seen["gsr_up"] and not seen["moving"]:
            return "anxiety", seen
        return "rest", seen

    def classifier_verdict(self, window):
        if not self.artifact or not self.artifact.get("confounder"):
            return None
        columns = self.artifact["confounder_features"]
        row = np.array([[float(window[name]) for name in columns]])
        return str(self.artifact["confounder"].predict(row)[0])

    def alert(self, verdict, seen, classifier):
        autonomic = []
        if seen["heart_rate_up"]:
            autonomic.append("heart rate")
        if seen["gsr_up"]:
            autonomic.append("skin conductance")
        if seen["respiration_up"]:
            autonomic.append("respiration")
        raised = listing(autonomic) if autonomic else "no autonomic channel"

        if verdict == "exercise":
            message = (
                f"Raised {raised} with sustained body motion, but EMG guarding is normal "
                "and no pain facial features are present. Movement rather than acute pain."
            )
        elif verdict == "anxiety":
            message = (
                f"Raised {raised}, but EMG is normal and no pain facial features are present. "
                "Possible anxiety rather than acute pain."
            )
        elif verdict == "sedated":
            carried = (
                f"The autonomic channel carries this estimate, with raised {raised}."
                if autonomic
                else "No autonomic rise is visible either, so the estimate rests on weak evidence."
            )
            message = (
                "Facial expression and muscle guarding are both suppressed under sedation. "
                f"{carried} Absent pain behaviour is not evidence of comfort."
            )
        elif verdict == "pain":
            evidence = []
            if seen["guarding"]:
                evidence.append("EMG guarding is elevated")
            if seen["pain_face"]:
                evidence.append("pain facial features are present")
            rise = f"with raised {raised}" if autonomic else "with no autonomic rise"
            message = f"{listing(evidence)}, {rise}. Pattern is consistent with nociception."
        else:
            message = "No autonomic, muscular or facial pain pattern in the three streams."

        if classifier and classifier != verdict:
            message += f" The classifier reads this window as {classifier}; the rule layer takes precedence."
        return message

    def combine(self, scores, window, context=None, layers=LAYERS, classifier=None):
        context = context or window.get("clinical_context") or DEFAULT_CONTEXT
        base = self.base_weights(context)
        composite = self.composite_weights(context, layers)
        quality = {stream: clamp(window[QUALITY_COLUMNS[stream]]) for stream in STREAMS}
        verdict, seen = self.rule_verdict(window, quality, context)
        if classifier is None:
            classifier = self.classifier_verdict(window)
        if verdict == "rest" and classifier in ("anxiety", "exercise"):
            verdict = classifier
        factor, reasons = self.confounder_factors(window, quality, verdict)
        if "attenuation" in layers:
            coefficient = {stream: clamp(quality[stream] * factor[stream]) for stream in STREAMS}
        else:
            coefficient = {stream: 1.0 for stream in STREAMS}
        final = {stream: composite[stream] * coefficient[stream] for stream in STREAMS}
        remaining = sum(final.values())

        if remaining < self.rules["minimum_total_weight"]:
            estimate = None
            status = INSUFFICIENT
        else:
            weighted = sum(scores[stream] * final[stream] for stream in STREAMS)
            estimate = round(clamp(weighted / remaining, 0.0, 10.0), 2)
            status = "OK"

        return {
            "status": status,
            "estimated_pain": estimate,
            "confidence": self.confidence(scores, quality, final, composite),
            "clinical_context": context,
            "stream_scores": {stream: round(scores[stream], 2) for stream in STREAMS},
            "signal_quality": {stream: round(quality[stream], 3) for stream in STREAMS},
            "attenuation": {stream: round(coefficient[stream], 3) for stream in STREAMS},
            "attenuation_reasons": reasons,
            "weights": {
                "base": {stream: round(base[stream], 4) for stream in STREAMS},
                "statistical": {stream: round(self.statistical[stream], 4) for stream in STREAMS},
                "ml": {stream: round(self.ml[stream], 4) for stream in STREAMS},
                "composite": {stream: round(composite[stream], 4) for stream in STREAMS},
                "final": {stream: round(final[stream], 4) for stream in STREAMS},
            },
            "remaining_weight": round(remaining, 4),
            "contributing_signals": self.contributions(final),
            "confounder_class": verdict,
            "classifier_class": classifier,
            "observations": {name: bool(value) for name, value in seen.items()},
        }

    def estimate(self, window, context=None, layers=LAYERS):
        scores = self.stream_scores(window)
        result = self.combine(scores, window, context, layers)
        result["confounder_alert"] = self.alert(
            result["confounder_class"], result["observations"], result["classifier_class"]
        )
        return result


def load(with_artifact=True):
    config = json.loads(CONFIG_PATH.read_text())
    learned = json.loads(LEARNED_PATH.read_text()) if LEARNED_PATH.exists() else None
    artifact = None
    if with_artifact and ARTIFACT_PATH.exists():
        import joblib

        artifact = joblib.load(ARTIFACT_PATH)
    return Fusion(config, learned, artifact)
