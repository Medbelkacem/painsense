import inspect
import json
from dataclasses import fields, replace
from pathlib import Path

import numpy as np

from backend.ai import features
from dataset.synthetic import generate, storage
from knowledge import context as context_module
from knowledge.context import ClinicalContext

FORBIDDEN = ("nrs", "self_report", "self-report", "report", "intensity")

LABEL_EXEMPT = {"onset_speed": "intensity"}


def test_no_feature_name_or_label_mentions_the_target():
    for name in features.NAMES:
        label = features.LABELS[name].lower()
        for word in FORBIDDEN:
            assert word not in name.lower(), name
            if LABEL_EXEMPT.get(name) != word:
                assert word not in label, features.LABELS[name]
    assert inspect.getsource(features._onset_speed).count("ctx.onset_speed") == 1
    assert "answers" not in inspect.getsource(features._onset_speed)


def test_the_context_has_no_attribute_for_the_score():
    names = [f.name for f in fields(ClinicalContext)] + [
        name for name in dir(ClinicalContext) if not name.startswith("_")
    ]
    assert not [name for name in names if "nrs" in name.lower()]


def test_the_dataset_feature_columns_exclude_the_target(tmp_path: Path):
    path, _ = generate.write(120, seed=3, patients=30, destination=tmp_path)
    table = storage.read_table(path / "integrated" / "train.parquet")
    feature_columns = [
        c for c in table.column_names if c.startswith(generate.FEATURE_COLUMN_PREFIX)
    ]
    assert generate.TARGET_COLUMN not in feature_columns
    assert len(feature_columns) == len(features.NAMES)

    target = np.asarray(table.column(generate.TARGET_COLUMN).to_pylist(), dtype=float)
    for column in feature_columns:
        values = np.asarray(table.column(column).to_pylist(), dtype=float)
        assert not np.array_equal(values, target, equal_nan=True), column


def test_changing_the_score_leaves_the_vector_unchanged():
    generator = generate.Generator(seed=5, patients=15, assessments=60)
    for _, record in list(generator.records())[:20]:
        before = features.vector(record.context)
        altered = replace(record, nrs=(record.nrs + 3) % 11)
        assert altered.nrs != record.nrs
        assert np.array_equal(features.vector(altered.context), before, equal_nan=True)

        assert "nrs" not in json.dumps(context_module.to_dict(altered.context)).lower()


def test_no_feature_reads_a_prediction_output():
    source = inspect.getsource(features)
    for word in ("prediction", "estimated", "PainPrediction"):
        assert word not in source, word


def test_each_visit_is_featurised_from_its_own_context_only(tmp_path: Path):
    path, _ = generate.write(80, seed=11, patients=10, destination=tmp_path)
    dataset = generate.load(path)

    signature = inspect.signature(features.vector)
    assert list(signature.parameters) == ["ctx"]

    for split in generate.SPLITS:
        for row in storage.iter_rows(path / "integrated" / f"{split}.parquet"):
            ctx = context_module.from_dict(json.loads(row["context_json"]))
            stored = np.array(
                [row[generate.feature_column(n)] for n in features.NAMES], dtype=float
            )
            assert np.array_equal(stored, features.vector(ctx), equal_nan=True)
    assert len(dataset) == 80
