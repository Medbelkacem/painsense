# The burned-surface research model

One model is trained in this repository. This document says what it is, what it was trained
on, what it scores, and — at greater length — what it must not be used for.

## What it estimates

The burned share of the body surface, as a fraction from 0 to 1, from two-dimensional body
mask projections.

## Why that is a real problem and not a pixel count

A burn seen from the front shows a projection of the body, and the burned fraction of that
projection is not the burned fraction of the body surface. A limb seen edge-on contributes
few pixels; a torso seen flat contributes many. Taking the projected ratio as the answer is
systematically wrong, and wrong in the unsafe direction — it **understates** the burn.

The size of that error, measured on the held-out subjects:

| Estimator | Mean absolute error, in surface-area fraction |
| --- | --- |
| Predict the training mean for every case | 0.2289 |
| Burned share of the projection, taken directly | 0.1502 |
| Burned share of the projection, with one scale factor fitted | 0.1276 |
| **This model** | **0.0225** |

The naive geometric estimate is out by about 12.8 percentage points of body surface. The
model is out by about 2.3. For context, 12 points is the difference between a burn below
most referral thresholds and one well above them.

## Training

| | |
| --- | --- |
| Dataset | `HLSS/MassHumanBurns` on the Hugging Face Hub, Apache-2.0 |
| Content | Synthetic renders of body meshes with burn regions, 5,000 subjects × 8 burn extents |
| Samples | 40,000 (one camera variant of four; front and back views) |
| Features | Two 24×24 downsampled mask grids plus 8 summary geometries |
| Target | The dataset's published surface fraction |
| Algorithm | `HistGradientBoostingRegressor`, 300 iterations |
| Split | `GroupShuffleSplit` by subject, 30,000 train / 10,000 test |
| Cross-validation | `GroupKFold`, 3 folds |

**Splits are grouped by subject throughout.** Each subject appears in 64 rows — eight burn
extents, four camera variants, two views — and a random split over rows would put the same
body in train and test. The training code asserts that no subject crosses the split and
raises if one does.

Masks are downsampled by block mean, not nearest neighbour. A thin burn on a limb can be
one pixel wide in the render, and nearest-neighbour sampling drops it entirely — which
would make the feature silently wrong for exactly the small burns that matter most.

## Measured performance

Held-out subjects, 10,000 samples from 1,250 subjects the model never saw:

| Metric | Value |
| --- | --- |
| MAE | 0.02253 |
| RMSE | 0.03119 |
| R² | 0.98725 |
| Pearson r | 0.99361 |
| Residual SD | 0.03118 |
| 3-fold grouped CV MAE | 0.02233 ± 0.00012 |

The cross-validated error agrees with the held-out error to four decimal places and the
spread across folds is 0.00012, so the figure is not an artefact of a lucky split.

What the error depends on, by the rise in MAE when a feature is shuffled:

| Feature | MAE increase when shuffled |
| --- | --- |
| `total_area` (front + back projected area) | 0.1043 |
| `front_rows_covered` (vertical extent) | 0.0285 |
| `front_area` | 0.0274 |
| `back_area` | 0.0045 |

That ordering is the model doing the expected thing: total projected area carries most of
the signal, and vertical extent carries the next most because it indicates *which* body
parts are involved, which is what determines the projection-to-surface correction.

## What it must not be used for

**It has never seen a real burn.** The dataset is synthetic renders of meshes. The model
carries no information about skin, erythema, blistering, eschar, or how any of those look
under a phone camera in a clinic.

**It takes masks, not photographs.** Its input is a clean binary mask of the burned region
against a body silhouette. Producing such a mask from a photograph is the segmentation task
— and that model does not exist here, because no openly licensed dataset for it could be
obtained. Without it there is no path from a photograph to this model's input.

**It is not clinically validated.** No comparison against clinician charting on real
patients has been made. An R² of 0.987 against synthetic ground truth says the model
reproduces the renderer's geometry, not that it would agree with a burns surgeon.

**It is not wired into the product.** `app.burns` calls no model. Depth, surface area and
healing are clinician-entered throughout, and the surface area shown in the interface comes
from the Lund–Browder or Rule of Nines chart with its breakdown visible. The registry entry
is `is_active=False` and nothing can activate it: the only activation path belongs to the
clinical pain estimator.

What it is genuinely good for: evidence that the projection-to-surface correction is
learnable and worth about 10 percentage points of accuracy over a pixel ratio. That is a
reason to pursue the segmentation half, not a result to put in front of a clinician.

## Reproducing it

```bash
# The imagery is ~1 GB, well over the per-dataset cap an unattended worker uses, so it is
# fetched by hand. Apache-2.0.
mkdir -p masshumanburns && cd masshumanburns
for f in burn_masks.7z labels.npy gender.json; do
  curl -L -C - -O "https://huggingface.co/datasets/HLSS/MassHumanBurns/resolve/main/$f"
done
7z x burn_masks.7z

cd ../backend && source .venv/bin/activate
python -m app.cli train-burn-tbsa --dataset ../masshumanburns --register --cv-folds 3
```

Seeded at 42 by default. Loading takes about 30 seconds and the fit about 40; three
cross-validation folds add roughly two minutes.

Without the dataset the command exits 2 with `Model not trained:` and the reason, rather
than producing a model with invented numbers.
