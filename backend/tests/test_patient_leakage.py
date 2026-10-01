from pathlib import Path

from database.models import ModelVersion
from dataset.synthetic import generate, storage


def test_no_patient_appears_in_two_splits(tmp_path: Path):
    path, manifest = generate.write(200, seed=21, patients=40, destination=tmp_path)
    seen: dict[str, set[str]] = {}
    for split in generate.SPLITS:
        for row in storage.iter_rows(
            path / "integrated" / f"{split}.parquet", ["patient_id", "split"]
        ):
            assert row["split"] == split
            seen.setdefault(row["patient_id"], set()).add(split)
    assert all(len(splits) == 1 for splits in seen.values())
    assert set(seen) == {f"SYN-{i + 1:06d}" for i in range(40)}
    assert (
        manifest["counts"]["split_patients"]["train"]
        > manifest["counts"]["split_patients"]["test"]
    )

    patients = storage.read_table(path / "patients" / "patient_master.parquet").to_pylist()
    for patient in patients:
        assert seen[patient["patient_id"]] == {patient["split"]}


def test_training_folds_are_grouped_by_patient(db):
    row = db.query(ModelVersion).filter_by(is_active=True).one()
    assert row.comparison
    assert all(entry["cv"] == "GroupKFold(patient)" for entry in row.comparison)
    assert row.n_validation > 0
