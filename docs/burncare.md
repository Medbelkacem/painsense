# BurnCare: burn assessment and wound follow-up

A module for documenting a burn, estimating the burned surface, tracking pain around wound
care, and recording what a clinician confirmed. It is built on the platform's existing
anatomy, pain scales, encrypted document store, audit chain and PDF generator rather than
alongside them.

## The separation the module is built around

Three kinds of statement are stored, and the schema never lets one become another:

| Attribution | What it means | Where it comes from |
| --- | --- | --- |
| `PATIENT` | The patient said it | Self-reported pain, incident account |
| `CLINICIAN` | A clinician decided it | Confirmed depth, surface area override, review |
| `MODEL` | Software suggested it | `suggested_depth`, image analysis |

A `BurnRegion` carries `depth` and `suggested_depth` in separate columns. Image analysis
writes only the second. The single route that moves a value across is
`POST /assessments/{id}/regions/{code}/confirm-depth`, which requires a clinician and
stamps `confirmed_by` and `confirmed_at` on the row. The audit entry records what the model
had suggested and whether the clinician agreed, so disagreement is measurable afterwards
rather than invisible.

A region whose depth is still `UNCERTAIN` carries no confirmation stamp even when a
clinician drew it. Marking an area is not deciding its depth.

## Surface area

Two charts over one region list, so a selection can be costed either way and compared.

**Lund–Browder** gives a head and lower limbs whose share of the body surface changes with
age. Every column totals exactly 100%, which the test suite asserts.

| Age band | Head | One thigh | One lower leg |
| --- | --- | --- | --- |
| under 1 | 19% | 5.5% | 5% |
| 1–4 | 17% | 6.5% | 5% |
| 5–9 | 13% | 8% | 5.5% |
| 10–14 | 11% | 8.5% | 6% |
| 15–17 | 9% | 9% | 6.5% |
| adult | 7% | 9.5% | 7% |

**Rule of Nines** divides an adult into blocks of nine. Selecting a forearm apportions the
arm's 9% by the forearm's share of the arm, so a partial selection does not cost a whole
limb.

**Palm method** takes the patient's own palm with fingers together as 1% of their body
surface, for burns too scattered to chart. Past about 15 palms it warns that charting
would be more accurate than counting.

### Two refusals, built in

*The adult chart is not applied to a child.* `RULE_OF_NINES` on a patient under 15 raises
`WrongChart` and the API returns 422 with the reason. An infant's head is 19% of the body
surface against an adult's 7%, so the adult chart understates a child's head burn by more
than half.

*Superficial epidermal injury is excluded.* It is excluded from every published method. It
is still counted and reported under its own heading, `excluded_superficial_percent`, so the
exclusion is visible instead of silent.

An area with no decided depth is counted and the estimate is marked `provisional`. An open
assessment should not read as reassuring because nobody has looked yet.

Every calculation stores its breakdown, assumptions, warnings and formula. A chart is
reference data that could be corrected later, and a decision taken last Tuesday has to stay
inspectable as the figure it actually was. A clinician's own total goes in
`clinician_percent` beside the computed one, never over it.

## Review flags

Flags ask a clinician to look. They are not triage decisions, and no rule clears a patient
— the absence of a flag is not a clinical opinion.

| Code | Raised when |
| --- | --- |
| `EXTENT` | At or above 10% for an adult, 5% for a child or an adult over 65 |
| `DEPTH` | Any deep partial or full-thickness area |
| `HIGH_RISK_SITE` | Head, neck, hands, feet or perineum, whatever the size |
| `CIRCUMFERENTIAL` | A circumferential burn, which can restrict circulation as swelling develops |
| `CAUSE` | Electrical or chemical, where the surface understates the damage |
| `AIRWAY` | Enclosed space, flame, or reported airway symptoms |
| `DEPTH_UNDECIDED` | An area has no decided depth, so the depth flags may be incomplete |
| `AGE_UNKNOWN` | No age recorded, so the chart and the extent threshold both assumed adult |

Flags are recomputed whenever the assessment changes and reconciled against what is stored.
A flag whose finding has gone is removed — unless a clinician acknowledged it, because an
acknowledgement records that someone looked and deleting it would erase that.

## Pain

Reuses the platform's existing scales: NRS, VAS, FPS-R for children, and the observational
scales for patients who cannot be asked. A self-report scale cannot be recorded as an
observation; the API returns 422.

A burn is painful in several distinct situations and one number does not describe it, so
rest, movement, during care, and before and after a dressing change are recorded
separately. They routinely differ by several points.

A full-thickness burn is insensate in the burned area itself. A low pain score over a deep
burn is not evidence of a less serious injury, and the depth reference says so where a
clinician will read it.

## Wound care and follow-up

Every clinical field is free text or a clinician-chosen value. The module documents what
was done; it proposes no cleaning solution, no dressing, no debridement and no medication
dose. Healing state is a clinician's judgement and is never inferred from two photographs
looking alike.

## Wound images

Bytes go to the existing encrypted document store — `MedicalDocument` already wraps a
per-file key and records a digest — under the `WOUND_PHOTO` kind. The `wound_images` row
carries the region, the assessment, the capture quality and the consent that covered the
capture. Consent withdrawal keeps the row and stamps `withdrawn_at`, so it stays possible
to say whether an image held at a given moment was held with consent.

## AI model status

**No model is used by this module.** Every depth, area and healing judgement is
clinician-entered and the model columns stay null. The surface area shown comes from the
Lund-Browder or Rule of Nines chart with its breakdown visible.

One model *was* trained, on the only burn dataset of the five named in the brief that
declares a licence: a burned-surface estimator fitted to the synthetic MassHumanBurns
renders (Apache-2.0). It reaches an MAE of 0.0225 in surface-area fraction against 0.1276
for the best naive pixel ratio, with splits grouped by subject and a 3-fold grouped CV of
0.02233 +/- 0.00012. It is recorded inactive, has never seen a real burn, takes clean masks
rather than photographs, and is not clinically validated. Full account, including what it
must not be used for: [docs/burn-model.md](burn-model.md).

The dataset side is wired through the platform's external dataset synchronisation
(`docs/external-datasets.md`), with connectors for the Hugging Face Hub and GitHub added
for the burn sources. What that pipeline actually found is instructive:

| Source | Licence as published | Outcome |
| --- | --- | --- |
| `HLSS/MassHumanBurns` | apache-2.0 | Retrieved and used for the surface-area model |
| `shubhambaid/skin-burn-dataset` | none declared | Catalogued, not retrieved |
| `VEDAs-Lab/EBIS` | no LICENSE file | Catalogued, not retrieved |
| `xjtu-mia/BurnAnalysis` | no LICENSE file | Catalogued, not retrieved |

Four of the five burn datasets named in the brief declare no licence at all, so an
automated pipeline correctly refuses them and records the route to request them instead.
That is why there is no segmentation or depth-classification model here rather than one
with invented metrics: the data for them could not be legally obtained.

## API

| Endpoint | Role | Purpose |
| --- | --- | --- |
| `GET /api/burns/reference` | any signed-in | Depth categories, regions with their share in every age band, causes, methods |
| `GET/PUT /api/burns/patients/{id}/consents` | clinical | Record and withdraw consent |
| `POST/GET /api/burns/incidents` | clinical | Record and list burn incidents |
| `GET /api/burns/incidents/{id}` | clinical | The incident with its whole timeline |
| `POST /api/burns/incidents/{id}/assessments` | clinical | Open an assessment |
| `GET /api/burns/assessments/{id}` | clinical | Assessment with regions, flags and calculations |
| `PUT/DELETE /api/burns/assessments/{id}/regions` | clinical | Add, update or remove a burned region |
| `POST .../regions/{code}/confirm-depth` | clinical | A clinician decides a depth |
| `POST /api/burns/assessments/{id}/tbsa` | clinical | Calculate and store a surface area estimate |
| `GET /api/burns/assessments/{id}/tbsa/compare` | clinical | Both charts side by side |
| `POST /api/burns/tbsa/{id}/override` | clinical | Record a clinician's own total |
| `POST /api/burns/assessments/{id}/submit\|confirm\|amend` | clinical | Review lifecycle |
| `POST /api/burns/alerts/{id}/acknowledge` | clinical | Acknowledge a flag |
| `POST/GET /api/burns/pain` | clinical | Pain reports |
| `POST/GET /api/burns/wound-care` | clinical | Wound care events |
| `POST /api/burns/follow-ups` | clinical | Follow-up visits |
| `GET /api/burns/dashboard` | admin | Aggregate counts, no patient-identifying content |

A confirmed assessment returns 409 to a silent change. Amend it to record a revision, so
the confirmed version stays on file.

## What is not built

Stated plainly rather than left to be discovered:

- **No 3D body viewer.** Regions are selected by code against the 19-region chart, and
  `BurnRegion.marks` stores free-hand coordinates for a viewer to use. The backend is ready
  for one; the viewer itself is not written.
- **No image segmentation model.** `ImageAnalysis` is the table a model writes to and
  `suggested_depth` is the column it fills. Nothing fills them yet.
- **No image upload route.** The encrypted store and the `wound_images` schema are in place;
  the multipart route and the quality checks are not.
- **No PDF report route.** `ClinicalReport` stores assembled content and the platform's PDF
  generator exists; the burn report template is not written.
- **No Arabic, French or English localisation.** All reference data is served from the API,
  so labels can be translated without touching the client, but no translations exist.
