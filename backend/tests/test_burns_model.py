"""The burn surface-area model's loader, features and split discipline.

Built against masks written in the test rather than against the real dataset, so the
module stays testable on a machine that has not downloaded 1.3 GB of renders. The one
thing these cannot check is whether the model is any good on real data; that is reported
from an actual training run and not asserted here.
"""

import json

import numpy as np
import pytest

from backend.burns import tbsa_model


def _write_mask(path, rows, cols, *, value=255, size=48):
    """A mask with a filled block, so its area and position are known exactly."""
    from PIL import Image

    frame = np.zeros((size, size), dtype=np.uint8)
    frame[rows[0] : rows[1], cols[0] : cols[1]] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame, mode="L").save(path)


@pytest.fixture
def dataset(tmp_path):
    """A miniature stand-in: 12 subjects, 8 burn extents, both views.

    The label is made proportional to the block area so the fixture is internally
    consistent; it says nothing about the real dataset's relationship.
    """
    subjects, levels, size = 12, 8, 48
    labels = np.zeros((subjects, levels), dtype=float)
    for subject in range(subjects):
        for level in range(levels):
            height = 2 + level * 4
            _write_mask(
                tmp_path / "burn_masks" / "front" / f"{subject}_{level}_0.png",
                (0, height),
                (0, size),
                size=size,
            )
            _write_mask(
                tmp_path / "burn_masks" / "back" / f"{subject}_{level}_0.png",
                (0, height),
                (0, size),
                size=size,
            )
            # A variant that must be ignored, written with a deliberately wrong area.
            _write_mask(
                tmp_path / "burn_masks" / "front" / f"{subject}_{level}_1.png",
                (0, size),
                (0, size),
                size=size,
            )
            labels[subject, level] = height / size
    np.save(tmp_path / "labels.npy", labels)
    (tmp_path / "gender.json").write_text(
        json.dumps({"male": list(range(6)), "female": list(range(6, 12))}), encoding="utf-8"
    )
    return tmp_path


def test_the_loader_pairs_every_mask_with_its_published_label(dataset):
    samples, meta = tbsa_model.load(dataset)

    assert meta["subjects_available"] == 12
    assert meta["samples"] == 96
    assert meta["has_back_view"] is True
    assert meta["gender_groups"] == {"male": 6, "female": 6}
    assert {sample.level for sample in samples} == set(range(8))


def test_only_the_chosen_camera_variant_is_loaded(dataset):
    """Variant 1 is written full-frame; loading it would make every area 1.0."""
    samples, _meta = tbsa_model.load(dataset)
    assert all(sample.front.mean() < 0.99 for sample in samples)
    assert len(samples) == 96


def test_downsampling_preserves_a_thin_burn(dataset):
    """Nearest-neighbour sampling drops a one-pixel limb burn; the block mean does not."""
    from PIL import Image

    path = dataset / "thin.png"
    frame = np.zeros((48, 48), dtype=np.uint8)
    frame[0:1, :] = 255
    Image.fromarray(frame, mode="L").save(path)

    mask = tbsa_model._load_mask(path)
    assert mask.sum() > 0, "a one-pixel-high burn vanished when downsampled"
    assert mask.mean() == pytest.approx(1 / 48, abs=0.01)


def test_mask_values_are_normalised(dataset):
    samples, _meta = tbsa_model.load(dataset)
    for sample in samples:
        assert sample.front.min() >= 0.0
        assert sample.front.max() <= 1.0
        assert sample.front.shape == (tbsa_model.GRID, tbsa_model.GRID)


def test_limiting_subjects_limits_the_load(dataset):
    samples, meta = tbsa_model.load(dataset, limit_subjects=3)
    assert meta["subjects_used"] == 3
    assert len(samples) == 24


def test_features_include_the_grid_and_the_summaries(dataset):
    samples, _meta = tbsa_model.load(dataset)
    x, names = tbsa_model.features(samples)

    expected = tbsa_model.GRID * tbsa_model.GRID * 2 + 8
    assert x.shape == (96, expected)
    assert len(names) == expected
    for name in ("front_area", "back_area", "total_area", "front_centroid_row"):
        assert name in names


def test_the_area_feature_matches_the_mask(dataset):
    samples, _meta = tbsa_model.load(dataset)
    x, names = tbsa_model.features(samples)
    column = names.index("front_area")
    for row, sample in zip(x, samples):
        assert row[column] == pytest.approx(sample.front.mean(), abs=1e-5)


def test_training_never_shares_a_subject_across_the_split(dataset):
    """The guard that makes the reported error mean anything."""
    samples, _meta = tbsa_model.load(dataset)
    result, model = tbsa_model.train(samples, seed=1, cv_folds=2)

    assert model is not None
    assert result.n_subjects == 12
    assert result.n_train + result.n_test == 96
    assert result.n_test > 0


def test_training_reports_both_baselines_to_compare_against(dataset):
    samples, _meta = tbsa_model.load(dataset)
    result = tbsa_model.train(samples, seed=1, cv_folds=2)[0].as_dict()

    assert "mean_baseline_mae" in result
    assert "pixel_ratio_calibrated_mae" in result
    assert "beats_mean_baseline" in result
    assert "beats_naive_pixel_ratio" in result
    assert result["cv_folds"] == 2, "grouped cross-validation must report its folds"


def test_the_result_states_that_the_data_is_synthetic(dataset):
    samples, _meta = tbsa_model.load(dataset)
    notes = " ".join(tbsa_model.train(samples, seed=1, cv_folds=2)[0].notes).casefold()
    assert "synthetic" in notes
    assert "not on photographs of real" in notes


def test_a_missing_label_file_is_reported_clearly(tmp_path):
    (tmp_path / "burn_masks" / "front").mkdir(parents=True)
    with pytest.raises(tbsa_model.DatasetUnavailable, match="labels.npy"):
        tbsa_model.load(tmp_path)


def test_missing_masks_are_reported_clearly(tmp_path):
    np.save(tmp_path / "labels.npy", np.zeros((2, 2)))
    with pytest.raises(tbsa_model.DatasetUnavailable, match="burn_masks"):
        tbsa_model.load(tmp_path)


def test_a_label_file_of_the_wrong_shape_is_refused(tmp_path):
    np.save(tmp_path / "labels.npy", np.zeros(10))
    (tmp_path / "burn_masks" / "front").mkdir(parents=True)
    with pytest.raises(tbsa_model.DatasetUnavailable, match="one row per subject"):
        tbsa_model.load(tmp_path)


def test_masks_with_no_matching_label_yield_nothing(tmp_path):
    np.save(tmp_path / "labels.npy", np.zeros((1, 1)))
    _write_mask(tmp_path / "burn_masks" / "front" / "99_9_0.png", (0, 4), (0, 48))
    with pytest.raises(tbsa_model.DatasetUnavailable, match="no mask matched"):
        tbsa_model.load(tmp_path)
