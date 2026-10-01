from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .registry import DATASET_ROOT, RAW_DIR

Chunks = Iterator[pd.DataFrame]

SYNTHETIC_ROOT = (
    DATASET_ROOT.parent / "backend" / "datasets" / "synthetic-v2-2026-09-30-seed42-p5000-n100000"
)
KAGGLE_RAW = RAW_DIR / "kaggle"


@dataclass(frozen=True)
class Source:
    dataset_id: str
    name: str
    data_source: str
    source_url: str
    origin_reference: str | None
    license: str
    synthetic: bool
    original_pain_scale: str
    nrs_mapping: str | None
    nrs_mapping_reason: str
    root: Path
    normalize: Callable[[Path], Chunks]
    provenance_notes: str

    def chunks(self, *, version: str | None = None, retrieved_at: str | None = None) -> Chunks:
        stamp = {
            "data_source": self.data_source,
            "dataset_id": self.dataset_id,
            "source_url": self.source_url,
            "license": self.license,
            "dataset_version": version,
            "retrieved_at": retrieved_at,
            "synthetic": self.synthetic,
            "provenance_notes": self.provenance_notes,
            "original_pain_scale": self.original_pain_scale,
        }
        for frame in self.normalize(self.root):
            stamped = pd.concat(
                [frame, pd.DataFrame(stamp, index=frame.index)], axis=1, copy=False
            )
            if self.nrs_mapping != "direct":
                stamped["self_reported_nrs"] = pd.NA
            yield stamped


def _cervical(root: Path) -> Chunks:
    raw = pd.read_csv(root / "Cervical_Pain_Dataset.csv")
    frame = pd.DataFrame(
        {
            "patient_id": "cervical:" + raw["Patient_ID"].astype(str),
            "assessment_id": "cervical:" + raw["Patient_ID"].astype(str) + ":1",
            "age": raw["Age"],
            "sex": raw["Gender"].map({"Male": "M", "Female": "F"}),
            "original_pain_score": raw["Pain_Score"],
            "pain_present": raw["Pain_Score"] > 0,
            "pain_region": "NECK",
            "pain_location": "CERVICAL_SPINE",
            "chronic_diseases": raw["Condition"],
            "movement": (
                "range_of_motion_deg=" + raw["Range_of_Motion"].round(1).astype(str)
                + "; angular_displacement_deg=" + raw["Angular_Displacement"].round(1).astype(str)
            ),
            "clinical_observations": "cervical motion capture with FFT spectral features",
        }
    )
    kinematics = (
        "Angular_Displacement", "Joint_Velocity", "Range_of_Motion", "Acceleration",
        "FFT_Frequency_1", "FFT_Frequency_2", "FFT_Frequency_3", "FFT_Peak_Power", "Target",
    )
    extra = raw[list(kinematics)].rename(columns=lambda name: f"src_{name.lower()}")
    yield pd.concat([frame, extra], axis=1, copy=False)


def _painspeech(root: Path) -> Chunks:
    raw = pd.read_csv(next(root.glob("PainSpeech-4*.csv")))
    frame = pd.DataFrame(
        {
            "patient_id": "painspeech:S" + raw["subject_id"].astype(int).astype(str).str.zfill(4),
            "assessment_id": "painspeech:" + raw["filename"].astype(str),
            "age": raw["age"],
            "sex": raw["gender"].str.upper().str[0],
            "original_pain_score": raw["class_value"],
            "pain_present": raw["class_label"].str.lower() != "no_pain",
            "voice_features": (
                "13 MFCC coefficients summarised as mean, std, max, min and delta; the "
                "values are in this source's own feature table"
            ),
            "clinical_observations": "elicited Arabic speech recording graded for pain level",
        }
    )
    carried = [
        column for column in raw.columns
        if column.startswith("mfcc") or column in {"class_label", "pain_level", "filename"}
    ]
    extra = raw[carried].rename(columns=lambda name: f"src_{name}")
    yield pd.concat([frame, extra], axis=1, copy=False)


_REGION_COLUMNS = {
    "f_region_head": "HEAD",
    "f_region_neck": "NECK",
    "f_region_chest": "CHEST",
    "f_region_back": "BACK",
    "f_region_abdomen": "ABDOMEN",
    "f_region_pelvis": "PELVIS",
    "f_region_upper_limb": "UPPER_LIMB",
    "f_region_lower_limb": "LOWER_LIMB",
    "f_region_systemic": "SYSTEMIC",
}

_SYNTHETIC_COLUMNS = [
    "patient_id", "assessment_id", "visit_index", "days_since_previous", "archetype",
    "scenario", "nrs", "split", "context_json", "f_hr", "f_resp_rate", "f_sbp", "f_dbp",
    "f_spo2", "f_temperature_c", *_REGION_COLUMNS,
]

_CONTEXT_FIELDS = (
    "age", "sex", "pain_onset", "pain_frequency", "pain_trajectory", "pain_duration",
    "pain_quality", "pain_radiation", "laterality", "anatomy_id", "pain_location",
    "aggravating_factors", "chronic_diseases", "medications", "functional_impact",
    "clinical_observations", "medication_effect", "recent_exercise",
)


def _laterality(sides: list[str]) -> str | None:
    unique = sorted({side for side in sides if side})
    return ";".join(unique) if unique else None


def _join(values: list) -> str | None:
    items = [str(value) for value in values if value]
    return ";".join(items) if items else None


def _from_context(contexts: list[dict], index: pd.Index) -> pd.DataFrame:
    derived: dict[str, list] = {key: [] for key in _CONTEXT_FIELDS}
    for context in contexts:
        impact = context.get("functional_impact") or {}
        medications = context.get("medications") or []
        confounders = context.get("confounders") or []
        derived["age"].append(context.get("age"))
        derived["sex"].append(context.get("sex"))
        derived["pain_onset"].append(context.get("onset"))
        derived["pain_frequency"].append(context.get("pattern"))
        derived["pain_trajectory"].append(context.get("course"))
        derived["pain_duration"].append(context.get("duration_hours"))
        derived["pain_quality"].append(_join(context.get("qualities") or []))
        derived["pain_radiation"].append("RADIATING" if context.get("radiates") else "NONE")
        derived["laterality"].append(_laterality(context.get("sides") or []))
        derived["anatomy_id"].append(_join(context.get("anatomical_structures") or []))
        derived["pain_location"].append(_join(context.get("pain_locations") or []))
        derived["aggravating_factors"].append(_join(context.get("factors") or []))
        derived["chronic_diseases"].append(_join(context.get("conditions") or []))
        derived["medications"].append(_join([m.get("class_code") for m in medications]))
        derived["medication_effect"].append(_join([m.get("pain_effect") for m in medications]))
        derived["functional_impact"].append(
            sum(impact.values()) / len(impact) if impact else None
        )
        derived["clinical_observations"].append(_join(context.get("symptoms") or []))
        derived["recent_exercise"].append("RECENT_EXERCISE" in confounders)
    return pd.DataFrame(derived, index=index)


def _synthetic(root: Path) -> Chunks:
    import pyarrow.parquet as pq

    for split in ("train", "validation", "test"):
        path = root / "integrated" / f"{split}.parquet"
        if not path.exists():
            continue
        handle = pq.ParquetFile(path)
        for batch in handle.iter_batches(batch_size=20_000, columns=_SYNTHETIC_COLUMNS):
            raw = batch.to_pandas()
            region = raw[list(_REGION_COLUMNS)].idxmax(axis=1).map(_REGION_COLUMNS)
            region = region.where(raw[list(_REGION_COLUMNS)].max(axis=1) > 0)
            frame = pd.DataFrame(
                {
                    "patient_id": "synthetic:" + raw["patient_id"].astype(str),
                    "assessment_id": "synthetic:" + raw["assessment_id"].astype(str),
                    "self_reported_nrs": raw["nrs"],
                    "original_pain_score": raw["nrs"],
                    "pain_present": raw["nrs"] > 0,
                    "pain_region": region,
                    "pain_type": raw["archetype"],
                    "heart_rate": raw["f_hr"],
                    "respiratory_rate": raw["f_resp_rate"],
                    "systolic_bp": raw["f_sbp"],
                    "diastolic_bp": raw["f_dbp"],
                    "spo2": raw["f_spo2"],
                    "body_temperature": raw["f_temperature_c"],
                    "src_visit_index": raw["visit_index"],
                    "src_days_since_previous": raw["days_since_previous"],
                    "src_scenario": raw["scenario"],
                    "src_generator_split": raw["split"],
                },
                index=raw.index,
            )
            contexts = [json.loads(payload) for payload in raw["context_json"]]
            context = _from_context(contexts, raw.index)
            yield pd.concat([frame, context], axis=1, copy=False)


def _empatica(root: Path) -> Chunks:
    raw = pd.read_csv(root / "pain_dataset_200P_4hz.csv")
    grouped = raw.groupby("person_ID")
    summary = grouped.agg(
        eda=("eda", "mean"),
        bvp=("bvp", "mean"),
        heart_rate=("hr", "mean"),
        skin_temperature=("temp", "mean"),
        pain_scale=("pain_scale", "first"),
        samples=("pain_scale", "size"),
    ).reset_index()
    spread = grouped[["eda", "bvp", "hr", "temp"]].std().add_suffix("_sd").reset_index()
    summary = summary.merge(spread, on="person_ID")

    subject = "e4:" + summary["person_ID"].astype(str)
    frame = pd.DataFrame(
        {
            "patient_id": subject,
            "assessment_id": subject + ":1",
            "original_pain_score": summary["pain_scale"],
            "pain_present": summary["pain_scale"] > 0,
            "heart_rate": summary["heart_rate"],
            "skin_temperature": summary["skin_temperature"],
            "eda": summary["eda"],
            "clinical_observations": "wrist-worn recording of electrodermal activity, blood "
            "volume pulse, heart rate and skin temperature",
        }
    )
    extra = summary[["samples", "bvp", "eda_sd", "bvp_sd", "hr_sd", "temp_sd"]].rename(
        columns=lambda name: f"src_{name}"
    )
    yield pd.concat([frame, extra], axis=1, copy=False)


def _knee(root: Path) -> Chunks:
    raw = pd.read_excel(next(root.glob("Mauritania_KneePain_*")))
    subject = "knee:" + pd.Series(range(1, len(raw) + 1)).astype(str).str.zfill(4)
    frame = pd.DataFrame(
        {
            "patient_id": subject,
            "assessment_id": subject + ":1",
            "age": raw["Age"],
            "sex": raw["Gender"].astype(str).str.upper().str[0],
            "self_reported_vas": raw["VAS"],
            "original_pain_score": raw["VAS"],
            "pain_present": raw["VAS"] > 0,
            "pain_region": "LOWER_LIMB",
            "pain_location": "KNEE",
            "pain_duration": raw["Disease_Duration_Months"] * 730.0,
            "chronic_diseases": raw[["Diabetes", "Hypertension"]].apply(
                lambda row: ";".join(
                    name.upper() for name, flag in row.items() if flag
                ) or None,
                axis=1,
            ),
            "sleep_deprivation": 4 - raw["Sleep_Quality"].clip(0, 4),
            "clinical_observations": "knee osteoarthritis cohort with WOMAC and "
            "Kellgren-Lawrence grading",
        }
    )
    carried = [
        "BMI", "KL_Grade", "WOMAC_Pain", "WOMAC_Function", "ROM", "Morning_Stiffness",
        "Swelling", "PHQ9", "GAD7", "Pain_Catastrophizing", "Previous_Knee_Injury",
        "Previous_Surgery", "Smoking", "Followup_VAS", "Recurrence",
    ]
    extra = raw[carried].rename(columns=lambda name: f"src_{name.lower()}")
    yield pd.concat([frame, extra], axis=1, copy=False)


def _migraine(root: Path) -> Chunks:
    raw = pd.read_csv(next(root.glob("migraine*.csv")))
    subject = "migraine:" + pd.Series(range(1, len(raw) + 1)).astype(str).str.zfill(4)
    symptoms = [
        "Nausea", "Vomit", "Phonophobia", "Photophobia", "Visual", "Sensory", "Dysphasia",
        "Dysarthria", "Vertigo", "Tinnitus", "Hypoacusis", "Diplopia", "Defect", "Ataxia",
        "Conscience", "Paresthesia",
    ]
    present = [name for name in symptoms if name in raw.columns]
    frame = pd.DataFrame(
        {
            "patient_id": subject,
            "assessment_id": subject + ":1",
            "age": raw["Age"],
            "original_pain_score": raw["Intensity"],
            "pain_present": raw["Intensity"] > 0,
            "pain_region": "HEAD",
            "pain_type": raw["Type"],
            "pain_frequency": raw["Frequency"].astype(str),
            "pain_duration": raw["Duration"] * 24.0,
            "clinical_observations": raw[present].apply(
                lambda row: ";".join(name.upper() for name, flag in row.items() if flag) or None,
                axis=1,
            ),
        }
    )
    extra = raw[[c for c in raw.columns if c not in {"Age", "Intensity", "Type"}]].rename(
        columns=lambda name: f"src_{name.lower()}"
    )
    yield pd.concat([frame, extra], axis=1, copy=False)


SOURCES: dict[str, Source] = {
    "kaggle_empatica_e4_pain": Source(
        dataset_id="kaggle_empatica_e4_pain",
        name="Pain prediction dataset, Empatica E4",
        data_source="Kaggle",
        source_url=(
            "https://www.kaggle.com/datasets/devashishmani1/pain-prediction-dataset-emphatica-e4"
        ),
        origin_reference="devashishmani1/pain-prediction-dataset-emphatica-e4",
        license="CC0: Public Domain",
        synthetic=False,
        original_pain_scale="pain_scale, integer 1-8, one value per subject",
        nrs_mapping=None,
        nrs_mapping_reason=(
            "The label runs 1 to 8 with no stated instrument or endpoints, so it cannot be "
            "asserted to be an NRS 0-10. It is preserved verbatim."
        ),
        root=KAGGLE_RAW / "devashishmani1__pain-prediction-dataset-emphatica-e4" / "extracted",
        normalize=_empatica,
        provenance_notes=(
            "Wrist-worn physiological recording, 200 subjects at 4 Hz. The 480 samples per "
            "subject are summarised into one record because the label is constant across "
            "them. An identical file is published again under omprakashyadav45; it is "
            "registered once."
        ),
    ),
    "kaggle_knee_pain_recurrence": Source(
        dataset_id="kaggle_knee_pain_recurrence",
        name="Knee pain recurrence cohort",
        data_source="Kaggle",
        source_url="https://www.kaggle.com/datasets/yutingpei/hearm-knee-pain-recurrence-dataset",
        origin_reference="yutingpei/hearm-knee-pain-recurrence-dataset",
        license="CC0: Public Domain",
        synthetic=True,
        original_pain_scale="VAS 0-10",
        nrs_mapping=None,
        nrs_mapping_reason=(
            "A visual analogue scale is not a numeric rating scale. The value is kept in "
            "self_reported_vas, which the schema holds separately, and no conversion is made."
        ),
        root=KAGGLE_RAW / "yutingpei__hearm-knee-pain-recurrence-dataset" / "extracted",
        normalize=_knee,
        provenance_notes=(
            "The publisher names the file Synthetic, so it is recorded as such. It carries no "
            "subject identifier, so one row is treated as one patient. Followup_VAS and "
            "Recurrence are recorded after the assessment and are kept out of the unified "
            "schema. The file is served with a .csv extension but is an xlsx workbook."
        ),
    ),
    "kaggle_migraine_symptoms": Source(
        dataset_id="kaggle_migraine_symptoms",
        name="Migraine symptom dataset",
        data_source="Kaggle",
        source_url="https://www.kaggle.com/datasets/ranzeet013/migraine-dataset",
        origin_reference="ranzeet013/migraine-dataset",
        license="Database: Open Database, Contents: Database Contents",
        synthetic=False,
        original_pain_scale="Intensity, ordinal 0-3",
        nrs_mapping=None,
        nrs_mapping_reason=(
            "A four-level ordinal intensity with no published mapping onto a 0-10 scale."
        ),
        root=KAGGLE_RAW / "ranzeet013__migraine-dataset" / "extracted",
        normalize=_migraine,
        provenance_notes=(
            "Migraine classification cohort. No subject identifier, so one row is treated as "
            "one patient. The same content is published again under gzdekzlkaya; it is "
            "registered once."
        ),
    ),
    "kaggle_ziya07_cervical_pain_assessment": Source(
        dataset_id="kaggle_ziya07_cervical_pain_assessment",
        name="Cervical Pain Assessment Dataset Using VR-MoCap",
        data_source="Kaggle",
        source_url=(
            "https://www.kaggle.com/datasets/ziya07/"
            "cervical-pain-assessment-dataset-using-vr-mocap"
        ),
        origin_reference="ziya07/cervical-pain-assessment-dataset-using-vr-mocap",
        license="CC0: Public Domain",
        synthetic=False,
        original_pain_scale="Cervical_Pain_Dataset Pain_Score, integer 0-9",
        nrs_mapping=None,
        nrs_mapping_reason=(
            "The publisher records an integer Pain_Score spanning 0-9 without naming the "
            "instrument or its endpoints, so it cannot be asserted to be an NRS 0-10. The "
            "value is preserved verbatim and self_reported_nrs stays null."
        ),
        root=KAGGLE_RAW / "ziya07__cervical-pain-assessment-dataset-using-vr-mocap" / "extracted",
        normalize=_cervical,
        provenance_notes=(
            "Published on Kaggle as a real dataset. The pipeline's own profiling found eight "
            "of its continuous columns indistinguishable from a uniform distribution, which is "
            "not what clinical measurement looks like; treat its realism as unverified."
        ),
    ),
    "kaggle_messaoudmezati_painspeech_4": Source(
        dataset_id="kaggle_messaoudmezati_painspeech_4",
        name="PainSpeech-4 Arabic Speech Dataset",
        data_source="Kaggle",
        source_url=(
            "https://www.kaggle.com/datasets/messaoudmezati/painspeech-4-arabic-speech-dataset"
        ),
        origin_reference="messaoudmezati/painspeech-4-arabic-speech-dataset",
        license="Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)",
        synthetic=False,
        original_pain_scale="PainSpeech-4 four-level ordinal class: no, low, middle, high",
        nrs_mapping=None,
        nrs_mapping_reason=(
            "The label is a four-level ordinal class, and the publisher documents no mapping "
            "from those levels onto a 0-10 scale. Inventing one would fabricate precision, so "
            "the class value is preserved verbatim and self_reported_nrs stays null."
        ),
        root=KAGGLE_RAW / "messaoudmezati__painspeech-4-arabic-speech-dataset" / "extracted",
        normalize=_painspeech,
        provenance_notes=(
            "Acoustic summary features from elicited Arabic speech, 194 subjects with "
            "repeated recordings. Used under CC BY-NC 4.0 for non-commercial research; not "
            "redistributed."
        ),
    ),
    "painsense_synthetic_v2": Source(
        dataset_id="painsense_synthetic_v2",
        name="PainSense synthetic assessment generator, v2",
        data_source="synthetic",
        source_url="local: backend/app/datasets/generate.py",
        origin_reference=None,
        license="project-internal",
        synthetic=True,
        original_pain_scale="generator-defined self-reported NRS 0-10",
        nrs_mapping="direct",
        nrs_mapping_reason=(
            "The generator defines nrs as the patient's self-reported 0-10 numeric rating "
            "scale, so it maps directly onto self_reported_nrs."
        ),
        root=SYNTHETIC_ROOT,
        normalize=_synthetic,
        provenance_notes=(
            "Synthetic data generated for research prototyping. Not clinical data and not "
            "representative of any real population."
        ),
    ),
}


def available() -> list[Source]:
    return [source for source in SOURCES.values() if source.root.exists()]


def dataset_id_for_reference(reference: str) -> str | None:
    for source in SOURCES.values():
        if source.origin_reference == reference:
            return source.dataset_id
    return None
