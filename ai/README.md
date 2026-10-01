# AI pipeline

Where each piece of the burn AI pipeline actually lives, and which pieces do not exist yet.

The dataset half of this is not a separate pipeline. It is the platform's external dataset
synchronisation (`backend/app/sync`, documented in `docs/external-datasets.md`), which
already does registration, source URLs, licence and access status, version tracking,
integrity digests, duplicate detection, validation and a synchronisation log. Building a
second one beside it would mean two registries disagreeing about what is held.

## What runs today

| Script | What it does |
| --- | --- |
| `ai/data/download_datasets.py` | Catalogues the configured burn datasets, reports each one's licence and access status, and retrieves those the licence permits |
| `ai/train/train_tbsa.py` | Fits the burned-surface model from an extracted dataset and records it in the model registry |

Both are thin entry points over the backend package, so there is one implementation of
each behaviour rather than two.

```bash
cd backend && source .venv/bin/activate

# Catalogue the burn sources without downloading anything
python ../ai/data/download_datasets.py --discover-only

# Fit the surface-area model and register it, inactive
python ../ai/train/train_tbsa.py --dataset /path/to/extracted/MassHumanBurns --register
```

## What does not exist, and why

The brief named five model tasks. One is trained. The other four are not, and the reason is
the same for all of them: **no openly licensed dataset for them could be obtained.**

| Task | State |
| --- | --- |
| Burn-region segmentation | Not trained. Needs annotated burn photographs; see the licence table below |
| Burn depth classification | Not trained. Same datasets, same obstacle |
| Body-region segmentation | Not trained |
| Burned surface estimation | **Trained.** See `docs/burn-model.md` |
| Pain estimation from physiology | Not trained. Deliberately out of scope — the wearable brief dropped AI pain estimation, and the patient's own report is the record |

What the dataset pipeline found when pointed at the sources the brief named:

| Source | Licence as the publisher states it | Outcome |
| --- | --- | --- |
| `HLSS/MassHumanBurns` | apache-2.0 | Retrievable. Used for the surface-area model |
| `shubhambaid/skin-burn-dataset` | none declared | Catalogued, not retrieved |
| `VEDAs-Lab/EBIS` | no LICENSE file | Catalogued, not retrieved |
| `xjtu-mia/BurnAnalysis` | no LICENSE file | Catalogued, not retrieved |
| Pediatric BurnNet (PMC article) | a paper, not a dataset release | Not a retrievable dataset |

Four of the five declare no licence. An unattended pipeline must not help itself to medical
imagery on that basis, so it catalogues them with the route to request access and fetches
nothing. The adapters are in place: if one of those publishers adds a LICENSE file, the
next synchronisation pass picks it up with no code change.

There are no `train_segmentation.py`, `train_depth_classifier.py` or `train_pain_model.py`
scripts here. Writing them against data nobody can legally obtain would produce files that
cannot be run and metrics that cannot be real, which is the outcome the brief asked to
avoid. The dataset adapters are the useful half of that work and they exist.

## Honest status in the product

The burn module works with no model at all: depth, surface area and healing are
clinician-entered throughout, and the model columns stay null. `ImageAnalysis` is the table
a segmentation model would write to and `BurnRegion.suggested_depth` is the column it would
fill. Nothing fills them.
