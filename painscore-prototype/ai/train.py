import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.fusion import ARTIFACT_PATH, CONFIG_PATH, LAYERS, LEARNED_PATH, Fusion
from ai.simulate import (
    ALL_FEATURES,
    CONFOUNDER_COLUMN,
    DATASET_PATH,
    LABEL_COLUMN,
    SELF_REPORT_COLUMN,
    STREAMS,
    STREAM_FEATURES,
    STREAM_NAMES,
    generate,
)

RESULTS_PATH = ROOT / "dataset" / "results.json"
TEST_PATIENTS = 11
FOLDS = 5
SEED = 7


def regressor():
    try:
        from xgboost import XGBRegressor

        return XGBRegressor(
            n_estimators=400,
            max_depth=5,
            learning_rate=0.06,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=SEED,
            n_jobs=4,
        ), "XGBRegressor"
    except ImportError:
        return RandomForestRegressor(n_estimators=300, random_state=SEED, n_jobs=4), "RandomForestRegressor"


def metrics(truth, prediction):
    truth = np.asarray(truth, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    error = prediction - truth
    return {
        "mae": round(float(np.mean(np.abs(error))), 3),
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 3),
        "pearson_r": round(float(pearsonr(truth, prediction)[0]), 3),
    }


def subgroup_masks(frame):
    failed = frame["failed_stream"].fillna("")
    return (
        ("all test windows", np.ones(len(frame), dtype=bool)),
        (
            "clean signal",
            ((failed == "") & (frame["c_occluded"] == 0) & (frame["scenario"] != "sedated")).to_numpy(),
        ),
        ("face occluded", (frame["c_occluded"] == 1).to_numpy()),
        ("sedated", (frame["scenario"] == "sedated").to_numpy()),
        ("one sensor down", (failed.str.len() == 1).to_numpy()),
        ("two or more down", (failed.str.len() >= 3).to_numpy()),
    )


def split_patients(frame):
    patients = np.sort(frame["patient_id"].unique())
    rng = np.random.default_rng(SEED)
    shuffled = rng.permutation(patients)
    return sorted(shuffled[TEST_PATIENTS:]), sorted(shuffled[:TEST_PATIENTS])


def out_of_fold_scores(frame, stream, model_factory):
    columns = list(STREAM_FEATURES[stream])
    features = frame[columns].to_numpy(dtype=float)
    target = frame[LABEL_COLUMN].to_numpy(dtype=float)
    groups = frame["patient_id"].to_numpy()
    predicted = np.zeros(len(frame), dtype=float)
    for train_index, holdout_index in GroupKFold(n_splits=FOLDS).split(features, target, groups):
        model, _ = model_factory()
        model.fit(features[train_index], target[train_index])
        predicted[holdout_index] = model.predict(features[holdout_index])
    return np.clip(predicted, 0.0, 10.0)


def stream_of(feature):
    for stream in STREAMS:
        if feature in STREAM_FEATURES[stream]:
            return stream
    raise KeyError(feature)


def grouped_importance(values, columns):
    totals = {stream: 0.0 for stream in STREAMS}
    for name, value in zip(columns, values):
        totals[stream_of(name)] += float(max(value, 0.0))
    total = sum(totals.values())
    if total <= 0.0:
        return {stream: 1.0 / len(STREAMS) for stream in STREAMS}
    return {stream: totals[stream] / total for stream in totals}


def learn_weights(train_frame):
    statistical = {}
    correlations = {}
    for stream in STREAMS:
        folded = out_of_fold_scores(train_frame, stream, regressor)
        correlation = pearsonr(train_frame[LABEL_COLUMN].to_numpy(dtype=float), folded)[0]
        correlations[stream] = round(float(correlation), 4)
        statistical[stream] = abs(float(correlation))
    total = sum(statistical.values())
    statistical = {stream: value / total for stream, value in statistical.items()}

    columns = list(ALL_FEATURES)
    features = train_frame[columns].to_numpy(dtype=float)
    target = train_frame[LABEL_COLUMN].to_numpy(dtype=float)
    model, model_name = regressor()
    model.fit(features, target)
    ml = grouped_importance(model.feature_importances_, columns)

    inner_patients = np.sort(train_frame["patient_id"].unique())
    held = set(inner_patients[-6:])
    inner_mask = ~train_frame["patient_id"].isin(held).to_numpy()
    checker, _ = regressor()
    checker.fit(features[inner_mask], target[inner_mask])
    shuffled = permutation_importance(
        checker,
        features[~inner_mask],
        target[~inner_mask],
        n_repeats=5,
        random_state=SEED,
        n_jobs=4,
    )
    permutation = grouped_importance(shuffled.importances_mean, columns)

    return {
        "statistical": {stream: round(statistical[stream], 4) for stream in STREAMS},
        "ml": {stream: round(ml[stream], 4) for stream in STREAMS},
        "detail": {
            "model": model_name,
            "pearson_r": correlations,
            "ml_permutation_check": {stream: round(permutation[stream], 4) for stream in STREAMS},
            "folds": FOLDS,
        },
    }


def fit_artifact(train_frame):
    scorers = {}
    features = {}
    model_name = ""
    for stream in STREAMS:
        columns = list(STREAM_FEATURES[stream])
        model, model_name = regressor()
        model.fit(train_frame[columns].to_numpy(dtype=float), train_frame[LABEL_COLUMN].to_numpy(dtype=float))
        scorers[stream] = model
        features[stream] = columns

    columns = list(ALL_FEATURES)
    classifier = RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=4)
    classifier.fit(train_frame[columns].to_numpy(dtype=float), train_frame[CONFOUNDER_COLUMN].to_numpy())

    return {
        "scorers": scorers,
        "features": features,
        "model": model_name,
        "confounder": classifier,
        "confounder_features": columns,
        "confounder_classes": sorted(set(train_frame[CONFOUNDER_COLUMN])),
    }


def fuse_column(fusion, rows, scores, layers, verdicts):
    estimates = []
    for index, row in enumerate(rows):
        row_scores = {stream: float(scores[stream][index]) for stream in STREAMS}
        result = fusion.combine(row_scores, row, row["clinical_context"], layers, verdicts[index])
        estimates.append(np.nan if result["estimated_pain"] is None else result["estimated_pain"])
    return np.array(estimates, dtype=float)


def evaluate(fusion, test_frame, artifact):
    rows = test_frame.to_dict("records")
    truth = test_frame[LABEL_COLUMN].to_numpy(dtype=float)
    scores = {
        stream: np.clip(
            artifact["scorers"][stream].predict(test_frame[artifact["features"][stream]].to_numpy(dtype=float)),
            0.0,
            10.0,
        )
        for stream in STREAMS
    }

    verdicts = [
        str(name)
        for name in artifact["confounder"].predict(
            test_frame[artifact["confounder_features"]].to_numpy(dtype=float)
        )
    ]

    full = fuse_column(fusion, rows, scores, LAYERS, verdicts)
    evaluable = ~np.isnan(full)

    results = {
        "streams": {
            stream: dict(metrics(truth[evaluable], scores[stream][evaluable]), name=STREAM_NAMES[stream])
            for stream in STREAMS
        },
        "simple_average": metrics(
            truth[evaluable], np.mean([scores[stream][evaluable] for stream in STREAMS], axis=0)
        ),
        "hybrid_fusion": metrics(truth[evaluable], full[evaluable]),
    }

    ablations = {}
    for dropped in LAYERS:
        kept = tuple(layer for layer in LAYERS if layer != dropped)
        column = fuse_column(fusion, rows, scores, kept, verdicts)
        usable = evaluable & ~np.isnan(column)
        scored = metrics(truth[usable], column[usable])
        scored["mae_delta"] = round(scored["mae"] - results["hybrid_fusion"]["mae"], 3)
        ablations[f"without_{dropped}"] = scored
    results["ablations"] = ablations

    simple = np.mean([scores[stream] for stream in STREAMS], axis=0)
    robustness = {}
    for name, mask in subgroup_masks(test_frame):
        usable = mask & evaluable
        entry = {"windows": int(mask.sum()), "insufficient_signal": int((mask & ~evaluable).sum())}
        if usable.any():
            for stream in STREAMS:
                entry[stream] = metrics(truth[usable], scores[stream][usable])["mae"]
            entry["simple_average"] = metrics(truth[usable], simple[usable])["mae"]
            entry["hybrid_fusion"] = metrics(truth[usable], full[usable])["mae"]
        robustness[name] = entry
    results["robustness"] = robustness

    reported = test_frame[SELF_REPORT_COLUMN].to_numpy(dtype=float)
    available = evaluable & ~np.isnan(reported)
    results["self_report_reference"] = dict(
        metrics(truth[available], reported[available]),
        windows=int(available.sum()),
        note="patient NRS against ground truth, never a model input",
    )

    results["windows"] = {
        "test_windows": int(len(test_frame)),
        "evaluated": int(evaluable.sum()),
        "insufficient_signal": int((~evaluable).sum()),
    }
    return results


def main():
    if not DATASET_PATH.exists():
        generate().to_csv(DATASET_PATH, index=False, float_format="%.4f")
    frame = pd.read_csv(DATASET_PATH)

    assert LABEL_COLUMN not in ALL_FEATURES
    assert SELF_REPORT_COLUMN not in ALL_FEATURES

    train_patients, test_patients = split_patients(frame)
    assert not set(train_patients) & set(test_patients)
    train_frame = frame[frame["patient_id"].isin(train_patients)].reset_index(drop=True)
    test_frame = frame[frame["patient_id"].isin(test_patients)].reset_index(drop=True)

    learned = learn_weights(train_frame)
    learned["detail"]["train_patients"] = train_patients
    learned["detail"]["test_patients"] = test_patients
    LEARNED_PATH.write_text(json.dumps(learned, indent=2) + "\n")

    artifact = fit_artifact(train_frame)
    joblib.dump(artifact, ARTIFACT_PATH)

    config = json.loads(CONFIG_PATH.read_text())
    fusion = Fusion(config, learned, artifact)
    results = evaluate(fusion, test_frame, artifact)
    results["split"] = {
        "train_patients": len(train_patients),
        "test_patients": len(test_patients),
        "train_windows": len(train_frame),
        "test_windows": len(test_frame),
        "model": artifact["model"],
    }
    results["learned_weights"] = {"statistical": learned["statistical"], "ml": learned["ml"]}
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n")

    print(f"train {len(train_patients)} patients / {len(train_frame)} windows")
    print(f"test  {len(test_patients)} patients / {len(test_frame)} windows")
    print()
    print(f"{'estimator':<26}{'MAE':>8}{'RMSE':>8}{'r':>8}")
    for stream in STREAMS:
        entry = results["streams"][stream]
        print(f"{'stream ' + stream + ' alone':<26}{entry['mae']:>8}{entry['rmse']:>8}{entry['pearson_r']:>8}")
    for name in ("simple_average", "hybrid_fusion"):
        entry = results[name]
        print(f"{name.replace('_', ' '):<26}{entry['mae']:>8}{entry['rmse']:>8}{entry['pearson_r']:>8}")
    print()
    for name, entry in results["ablations"].items():
        print(f"{name.replace('_', ' '):<26}{entry['mae']:>8}{entry['rmse']:>8}{entry['pearson_r']:>8}  MAE {entry['mae_delta']:+}")
    print()
    print(f"{'subgroup':<22}{'n':>6}{'A':>7}{'B':>7}{'C':>7}{'avg':>7}{'fusion':>8}{'refused':>9}")
    for name, entry in results["robustness"].items():
        if "hybrid_fusion" not in entry:
            continue
        print(
            f"{name:<22}{entry['windows']:>6}"
            + "".join(f"{entry[stream]:>7.2f}" for stream in STREAMS)
            + f"{entry['simple_average']:>7.2f}{entry['hybrid_fusion']:>8.2f}{entry['insufficient_signal']:>9}"
        )
    print()
    print(f"statistical weights {learned['statistical']}")
    print(f"ml weights          {learned['ml']}")
    print(f"insufficient signal {results['windows']['insufficient_signal']} of {results['windows']['test_windows']} windows")


if __name__ == "__main__":
    main()
