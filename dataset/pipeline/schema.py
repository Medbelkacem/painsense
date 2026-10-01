from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

TARGET = "self_reported_nrs"

FIELDS: dict[str, tuple[str, str]] = {
    "patient_id": ("string", "identity"),
    "assessment_id": ("string", "identity"),
    "timestamp": ("datetime64[ns, UTC]", "identity"),
    "age": ("Float64", "demographics"),
    "sex": ("string", "demographics"),
    "pain_present": ("boolean", "label"),
    "self_reported_nrs": ("Float64", "label"),
    "self_reported_vas": ("Float64", "label"),
    "original_pain_score": ("Float64", "label"),
    "original_pain_scale": ("string", "label"),
    "pain_type": ("string", "pain_character"),
    "pain_onset": ("string", "temporal"),
    "pain_duration": ("Float64", "temporal"),
    "pain_frequency": ("string", "temporal"),
    "pain_trajectory": ("string", "temporal"),
    "pain_region": ("string", "pain_location"),
    "pain_location": ("string", "pain_location"),
    "anatomy_id": ("string", "pain_location"),
    "laterality": ("string", "pain_location"),
    "pain_quality": ("string", "pain_character"),
    "pain_radiation": ("string", "pain_character"),
    "aggravating_factors": ("string", "pain_character"),
    "relieving_factors": ("string", "pain_character"),
    "heart_rate": ("Float64", "physiology"),
    "hrv": ("Float64", "physiology"),
    "respiratory_rate": ("Float64", "physiology"),
    "systolic_bp": ("Float64", "physiology"),
    "diastolic_bp": ("Float64", "physiology"),
    "spo2": ("Float64", "physiology"),
    "skin_temperature": ("Float64", "physiology"),
    "body_temperature": ("Float64", "physiology"),
    "eda": ("Float64", "biosignal"),
    "gsr": ("Float64", "biosignal"),
    "emg": ("Float64", "biosignal"),
    "movement": ("string", "behavioural"),
    "facial_expression": ("string", "behavioural"),
    "voice_features": ("string", "behavioural"),
    "anxiety": ("Float64", "confounder"),
    "stress": ("Float64", "confounder"),
    "fear": ("Float64", "confounder"),
    "sleep_deprivation": ("Float64", "confounder"),
    "recent_exercise": ("boolean", "confounder"),
    "medication_effect": ("string", "confounder"),
    "chronic_diseases": ("string", "history"),
    "medications": ("string", "history"),
    "functional_impact": ("Float64", "functional"),
    "clinical_observations": ("string", "clinical"),
    "data_source": ("string", "provenance"),
    "dataset_id": ("string", "provenance"),
    "source_url": ("string", "provenance"),
    "license": ("string", "provenance"),
    "dataset_version": ("string", "provenance"),
    "retrieved_at": ("string", "provenance"),
    "synthetic": ("boolean", "provenance"),
    "provenance_notes": ("string", "provenance"),
}

REQUIRED = ("patient_id", "assessment_id", "data_source", "dataset_id", "synthetic")

PROVENANCE_FIELDS = tuple(n for n, (_, group) in FIELDS.items() if group == "provenance")

PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "age": (0, 120),
    "self_reported_nrs": (0, 10),
    "self_reported_vas": (0, 100),
    "heart_rate": (20, 250),
    "respiratory_rate": (4, 70),
    "systolic_bp": (50, 260),
    "diastolic_bp": (20, 180),
    "spo2": (50, 100),
    "skin_temperature": (20, 45),
    "body_temperature": (28, 44),
    "functional_impact": (0, 4),
    "pain_duration": (0, 525600),
}

LABEL_POLICY = (
    "self_reported_nrs is populated only where the publisher documents a 0-10 numeric rating "
    "scale. Any other pain label is kept verbatim in original_pain_score with its scale named "
    "in original_pain_scale; no conversion between scales is invented."
)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype=dtype) for name, (dtype, _) in FIELDS.items()})


def _cast(series: pd.Series, dtype: str) -> pd.Series:
    if dtype.startswith("datetime64"):
        converted = pd.to_datetime(series, errors="coerce", utc=True)
        return converted.astype(dtype)
    if dtype == "Float64":
        return pd.to_numeric(series, errors="coerce").astype("Float64")
    if dtype == "boolean":
        return series.astype("object").where(series.notna(), pd.NA).astype("boolean")
    return series.astype("string")


def conform(frame: pd.DataFrame, *, dataset_id: str) -> pd.DataFrame:
    missing_required = [name for name in REQUIRED if name not in frame.columns]
    if missing_required:
        raise ValueError(f"{dataset_id}: normalized frame is missing {missing_required}")

    conformed = pd.DataFrame(index=frame.index)
    for name, (dtype, _) in FIELDS.items():
        if name in frame.columns:
            conformed[name] = _cast(frame[name], dtype)
        else:
            conformed[name] = pd.Series(pd.NA, index=frame.index, dtype=dtype)
    return conformed


def dropped_columns(frame: pd.DataFrame) -> list[str]:
    return sorted(set(frame.columns) - set(FIELDS))


def describe() -> dict[str, Any]:
    return {
        "target": TARGET,
        "required": list(REQUIRED),
        "field_count": len(FIELDS),
        "fields": [
            {"name": name, "dtype": dtype, "group": group}
            for name, (dtype, group) in FIELDS.items()
        ],
        "plausible_ranges": {k: list(v) for k, v in PLAUSIBLE_RANGES.items()},
        "label_policy": LABEL_POLICY,
    }


DEFAULT_SEED = 42
DEFAULT_RATIOS = (0.70, 0.15, 0.15)
SPLIT_NAMES = ("train", "validation", "test")
UNLABELLED = "unlabelled"

EXCLUDED_GROUPS = frozenset({"identity", "label", "provenance"})

MULTI_VALUE_COLUMNS = frozenset({
    "pain_quality", "anatomy_id", "pain_location", "aggravating_factors",
    "relieving_factors", "chronic_diseases", "medications", "clinical_observations",
    "medication_effect", "laterality",
})

CARRIED = ("patient_id", "assessment_id", "dataset_id", "data_source", "synthetic", "split")

MAX_LEVELS = 20
MAX_TOKENS = 40


def _as_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Float64")


def _patient_strata(frame: pd.DataFrame, patient_column: str, label_column: str) -> pd.Series:
    if label_column not in frame.columns:
        return pd.Series(UNLABELLED, index=frame[patient_column].dropna().unique())

    labels = pd.to_numeric(frame[label_column], errors="coerce")
    per_patient = labels.groupby(frame[patient_column]).mean()
    bands = pd.cut(
        per_patient,
        bins=[-np.inf, 2, 4, 6, 8, np.inf],
        labels=["0-2", "2-4", "4-6", "6-8", "8+"],
    )
    return bands.astype("object").fillna(UNLABELLED)


def assign(
    frame: pd.DataFrame,
    *,
    patient_column: str = "patient_id",
    label_column: str = TARGET,
    ratios: tuple[float, float, float] = DEFAULT_RATIOS,
    seed: int = DEFAULT_SEED,
) -> tuple[pd.Series, dict[str, Any]]:
    if patient_column not in frame.columns:
        raise ValueError(f"{patient_column!r} is required to split at patient level")
    if abs(sum(ratios) - 1.0) > 1e-9:
        raise ValueError(f"split ratios must sum to 1, got {ratios}")

    strata = _patient_strata(frame, patient_column, label_column)
    rng = np.random.default_rng(seed)
    assignment: dict[str, str] = {}

    for stratum in sorted(set(strata.astype(str))):
        patients = sorted(str(p) for p, value in strata.items() if str(value) == stratum)
        order = rng.permutation(len(patients))
        shuffled = [patients[index] for index in order]
        boundaries = np.cumsum([round(ratio * len(shuffled)) for ratio in ratios[:-1]])
        for position, patient in enumerate(shuffled):
            if position < boundaries[0]:
                assignment[patient] = SPLIT_NAMES[0]
            elif position < boundaries[1]:
                assignment[patient] = SPLIT_NAMES[1]
            else:
                assignment[patient] = SPLIT_NAMES[2]

    keys = frame[patient_column].astype("string")
    splits = keys.map(assignment).astype("string")

    description = {
        "method": "stratified patient-level assignment",
        "unit_of_assignment": "patient",
        "patient_column": patient_column,
        "stratified_on": label_column,
        "strata": sorted(set(strata.astype(str))),
        "ratios": dict(zip(SPLIT_NAMES, ratios)),
        "seed": seed,
        "patients_assigned": len(assignment),
        "records_assigned": int(splits.notna().sum()),
        "records_unassigned": int(splits.isna().sum()),
    }
    return splits, description


def summarise(frame: pd.DataFrame, *, split_column: str = "split") -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in SPLIT_NAMES:
        subset = frame[frame[split_column] == name]
        labels = pd.to_numeric(subset.get(TARGET), errors="coerce")
        summary[name] = {
            "records": len(subset),
            "patients": int(subset["patient_id"].nunique()) if "patient_id" in subset else None,
            "records_with_target": int(labels.notna().sum()) if labels is not None else 0,
            "target_mean": (
                round(float(labels.mean()), 4)
                if labels is not None and labels.notna().any() else None
            ),
            "target_std": (
                round(float(labels.std()), 4)
                if labels is not None and labels.notna().sum() > 1 else None
            ),
        }
    return summary


def candidate_features() -> tuple[list[str], list[str], list[str]]:
    numeric, categorical, multi = [], [], []
    for name, (dtype, group) in FIELDS.items():
        if group in EXCLUDED_GROUPS:
            continue
        if name in MULTI_VALUE_COLUMNS:
            multi.append(name)
        elif dtype in {"Float64", "boolean"}:
            numeric.append(name)
        else:
            categorical.append(name)
    return numeric, categorical, multi


@dataclass
class Encoder:
    numeric: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    multi_value: list[str] = field(default_factory=list)
    medians: dict[str, float] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    stds: dict[str, float] = field(default_factory=dict)
    levels: dict[str, list[str]] = field(default_factory=dict)
    tokens: dict[str, list[str]] = field(default_factory=dict)
    all_null: list[str] = field(default_factory=list)

    def fit(self, train: pd.DataFrame) -> Encoder:
        numeric, categorical, multi = candidate_features()
        self.numeric = [name for name in numeric if name in train.columns]
        self.categorical = [name for name in categorical if name in train.columns]
        self.multi_value = [name for name in multi if name in train.columns]

        for name in list(self.numeric):
            values = _as_float(train[name])
            if values.notna().sum() == 0:
                self.all_null.append(name)
                self.numeric.remove(name)
                continue
            self.medians[name] = float(values.median())
            self.means[name] = float(values.mean())
            deviation = float(values.std())
            self.stds[name] = deviation if deviation and deviation > 1e-12 else 1.0

        for name in list(self.categorical):
            counts = train[name].astype("string").dropna().value_counts()
            if counts.empty:
                self.all_null.append(name)
                self.categorical.remove(name)
                continue
            self.levels[name] = [str(level) for level in counts.head(MAX_LEVELS).index]

        for name in list(self.multi_value):
            exploded = train[name].astype("string").dropna().str.split(";").explode().str.strip()
            counts = exploded[exploded != ""].value_counts()
            if counts.empty:
                self.all_null.append(name)
                self.multi_value.remove(name)
                continue
            self.tokens[name] = [str(token) for token in counts.head(MAX_TOKENS).index]

        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        blocks: list[pd.DataFrame] = [
            frame[[name for name in CARRIED if name in frame.columns]].reset_index(drop=True),
            frame[[TARGET]].reset_index(drop=True),
        ]

        numeric_block: dict[str, Any] = {}
        for name in self.numeric:
            values = _as_float(frame[name])
            numeric_block[f"{name}_missing"] = values.isna().astype("int8").to_numpy()
            filled = values.fillna(self.medians[name]).astype("float64")
            numeric_block[name] = ((filled - self.means[name]) / self.stds[name]).to_numpy()
        if numeric_block:
            blocks.append(pd.DataFrame(numeric_block))

        categorical_block: dict[str, Any] = {}
        for name in self.categorical:
            values = frame[name].astype("string")
            for level in self.levels[name]:
                categorical_block[f"{name}={level}"] = (
                    (values == level).fillna(False).astype("int8").to_numpy()
                )
            categorical_block[f"{name}=__other__"] = (
                (values.notna() & ~values.isin(self.levels[name]))
                .fillna(False).astype("int8").to_numpy()
            )
            categorical_block[f"{name}_missing"] = values.isna().astype("int8").to_numpy()
        if categorical_block:
            blocks.append(pd.DataFrame(categorical_block))

        multi_block: dict[str, Any] = {}
        for name in self.multi_value:
            values = frame[name].astype("string").fillna("")
            for token in self.tokens[name]:
                pattern = rf"(?:^|;)\s*{re.escape(token)}\s*(?:;|$)"
                multi_block[f"{name}:{token}"] = (
                    values.str.contains(pattern, regex=True, na=False).astype("int8").to_numpy()
                )
            multi_block[f"{name}_count"] = (
                values.apply(lambda text: len([p for p in text.split(";") if p.strip()]))
                .astype("int16")
                .to_numpy()
            )
        if multi_block:
            blocks.append(pd.DataFrame(multi_block))

        return pd.concat(blocks, axis=1)

    def feature_columns(self, encoded: pd.DataFrame) -> list[str]:
        reserved = {*CARRIED, TARGET}
        return [column for column in encoded.columns if column not in reserved]

    def describe(self) -> dict[str, Any]:
        return {
            "excluded_schema_groups": sorted(EXCLUDED_GROUPS),
            "carried_through_unencoded": list(CARRIED),
            "numeric_features": self.numeric,
            "categorical_features": self.categorical,
            "multi_value_features": self.multi_value,
            "dropped_all_null_in_train": sorted(self.all_null),
            "numeric_handling": (
                "median imputation plus a per-column missing indicator, then z-score "
                "standardisation; the median, mean and standard deviation are computed on the "
                "training split only"
            ),
            "categorical_handling": (
                f"indicator per level, up to {MAX_LEVELS} levels seen in training, plus an "
                "__other__ indicator and a missing indicator"
            ),
            "multi_value_handling": (
                f"presence indicator per token, up to {MAX_TOKENS} tokens seen in training, "
                "plus a token count"
            ),
            "fitted_levels": {name: len(levels) for name, levels in self.levels.items()},
            "fitted_tokens": {name: len(tokens) for name, tokens in self.tokens.items()},
        }
