# Pain Score

A research prototype for the PAIN SCORE hackathon. It estimates pain intensity on a 0-10
scale by fusing three non-invasive sensor streams, and it decides window by window how
much each stream deserves to count.

**This is an AI-assisted estimation tool, not a medical device.** It is not validated, it
has never seen a real patient, and it must not be used to make a clinical decision.

**The patient's self-report is never a model input.** It is recorded in its own column,
kept out of the feature set, and shown next to the estimate so the two can be compared.
`ai/train.py` asserts that it is absent from the features before it trains anything.

## The problem

A patient who is anxious and a patient who is in pain look almost the same to a wrist
sensor. In the dataset here, anxiety produces a heart rate of 84 bpm, skin conductance of
7.75 µS and a Pain Stress Index of 36; pain at 7-10 produces 86 bpm, 7.16 µS and 37. A
patient who is exercising looks worse still, with a Pain Stress Index of 53, higher than
real pain. What separates them is muscle guarding and facial expression, which live on
different sensors, and those sensors fail: faces get covered, electrodes slip, patches
come unstuck.

So the question is not how to read one sensor well. It is how much to trust each sensor
right now, and when to stop answering.

## Three streams

Each stream produces a score on the same 0-10 scale and a quality index between 0 and 1.

**A, neuro-muscular.** Simulated EEG band power (alpha, beta, theta, and the theta/beta
ratio) and surface EMG amplitude in µV, which rises when a muscle guards against pain.
This is the stream that still says something when the patient is unconscious.

**B, smart patch.** Autonomic signals: heart rate and HRV from PPG, tonic GSR in µS with
phasic peak counts, skin temperature, respiration rate and an IMU motion index, combined
into a Pain Stress Index. The patch also reports its therapy outputs, TENS, vibration,
thermotherapy and photobiomodulation, as state flags. This is the stream the confounders
attack.

**C, contextual AI.** Facial action units AU4, AU6, AU7, AU9, AU10 and AU43 on the 0-5
FACS intensity scale, contactless rPPG and voice features. This is the most informative
stream when the face is visible and useless when it is not.

## The four layers

The weighting is in `ai/fusion.py` and its constants are in `config/weights.json`, so
every number below can be changed without touching the code.

**Layer 1, clinical heuristics.** A prior set by the care context, applied at runtime:

| context | A | B | C |
| --- | --- | --- | --- |
| unconscious, sedated | 0.60 | 0.30 | 0.10 |
| conscious, emergency | 0.20 | 0.30 | 0.50 |
| conscious, ward | 0.30 | 0.35 | 0.35 |

**Layer 2, statistical.** Learned offline on the training split only. For each stream,
the absolute Pearson correlation between its out-of-fold score and the pain label,
normalised across streams. The three correlations here are 0.794, 0.611 and 0.838, giving
weights of 0.354, 0.272 and 0.374.

**Layer 3, machine-learned importance.** Also offline, also training split only. One
XGBoost regressor over all 30 features, with its gain importances summed per stream and
normalised: 0.432, 0.154 and 0.413. Permutation importance is computed on an inner
hold-out as a cross-check and recorded beside it. Both layers are written to
`config/learned_weights.json`.

**Layer 4, real-time attenuation.** A coefficient C between 0 and 1 per stream, computed
for the window in front of you as `signal_quality × confounder_factor`:

| condition | effect |
| --- | --- |
| EEG quality at or below 0.35 | C_A = 0 |
| IMU motion at or above 0.5 | C_B = 0.3 |
| the window reads as exercise or anxiety | C_B = 0.35 |
| smiling or talking detected | C_C = 0.2 |
| face occluded | C_C = 0.25 |
| lighting below 0.45 | C_C scaled by how dark it is |

The third rule is what connects the confounder detector to the weighting. When the rule
layer concludes that a raised heart rate belongs to exercise or anxiety rather than to
pain, the autonomic stream stops counting for that window.

Then:

```
W_comp  = 0.4·W_base + 0.3·W_stat + 0.3·W_ml      normalised to 1
W_final = W_comp × C
GPS     = Σ(score × W_final) / Σ(W_final)         clipped to [0, 10]
```

If `Σ(W_final)` falls below 0.05 the system returns **INSUFFICIENT SIGNAL** instead of a
number. It refuses on 22 of the 1,760 test windows, which are the ones where all three
sensors are down.

**Confidence** combines three things the system can actually know: mean signal quality
(0.4), how much weight survived attenuation (0.3), and how much the three streams agree,
as one minus their normalised spread (0.3).

## Confounder detection

A rule layer and a classifier, in that order. The rules look for muscle guarding and
facial pain signs, and an observation only counts if the sensor carrying it is readable,
so the system never claims to see EMG guarding on an electrode it has declared dead. If
either pain-specific sign is present the verdict is pain. If the patient is sedated, the
verdict says so rather than reporting calm, because a sedated patient shows neither
guarding nor expression and absent pain behaviour is not evidence of comfort. Otherwise
motion plus raised respiration reads as exercise, and raised heart rate with raised skin
conductance reads as anxiety.

A random forest trained on all 30 features runs alongside. It can refine a verdict of rest
into exercise or anxiety, but it can never create or overturn a verdict of pain: the rules
keep the veto on the safety-relevant call. The alert comes out in plain language:

> Raised heart rate and skin conductance, but EMG is normal and no pain facial features
> are present. Possible anxiety rather than acute pain.

> Facial expression and muscle guarding are both suppressed under sedation. The autonomic
> channel carries this estimate, with raised skin conductance. Absent pain behaviour is
> not evidence of comfort.

## What it scores

Trained on 25 patients, evaluated on 11 the model has never met, 1,760 windows. Run
`python ai/train.py` to reproduce; the numbers land in `dataset/results.json` and on the
dashboard.

| estimator | MAE | RMSE | r |
| --- | --- | --- | --- |
| stream A alone | 1.314 | 1.913 | 0.831 |
| stream B alone | 1.999 | 2.672 | 0.631 |
| stream C alone | 1.065 | 1.591 | 0.887 |
| simple average | 1.266 | 1.596 | 0.915 |
| **4-layer hybrid fusion** | **1.157** | **1.491** | **0.922** |
| patient self-report, for reference | 0.783 | 1.205 | 0.937 |

Removing one layer at a time, against the full fusion:

| ablation | MAE | Δ MAE |
| --- | --- | --- |
| without layer 1, clinical base | 1.121 | −0.036 |
| without layer 2, statistical | 1.155 | −0.002 |
| without layer 3, ML importance | 1.198 | +0.041 |
| without layer 4, attenuation | 1.201 | +0.044 |

Layers 3 and 4 earn their place. Layer 2 is close to neutral, which is what normalising
three similar correlations produces. Layer 1 costs 0.036 MAE: it is a clinical safety
prior that stops the model abandoning a modality, and it is not free.

The honest headline is that stream C alone scores better than the fusion on aggregate
MAE, 1.065 against 1.157. That comparison holds only while the camera can see the face:

| condition | windows | A | B | C | simple avg | fusion | refused |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all test windows | 1,760 | 1.31 | 2.00 | 1.06 | 1.27 | 1.16 | 22 |
| clean signal | 1,218 | 1.22 | 2.05 | 0.91 | 1.19 | 1.09 | 0 |
| face occluded | 368 | 1.33 | 2.07 | 1.56 | 1.50 | 1.36 | 22 |
| sedated | 132 | 1.88 | 1.40 | 1.50 | 1.35 | 1.37 | 1 |
| one sensor down | 99 | 1.54 | 2.09 | 1.55 | 1.64 | 1.19 | 1 |
| two or more down | 77 | 1.97 | 1.91 | 1.65 | 1.77 | 1.48 | 20 |

The fusion beats the simple average in every condition, and when a sensor goes down it
beats every individual stream. A face-only estimator has nothing to fall back on; four of
the 36 virtual patients have their face covered for most of their stay, and the split is
by patient, so those patients are only ever seen at test time.

## Security

`security/security.py` picks the strongest post-quantum provider available and says which
one it used. With liboqs-python it uses that; otherwise it uses `kyber-py` and
`dilithium-py`, which are pure-Python implementations of the same FIPS standards. If
neither is installed it falls back to X25519 and Ed25519 and prints a warning that the
records are not protected against a quantum adversary, and the dashboard shows an orange
banner saying so.

- **ML-KEM-768** for key exchange, 1,088-byte encapsulation, HKDF-SHA256 to the session key
- **AES-256-GCM** for every stored estimate, with the pseudonymous subject id as
  associated data
- **ML-DSA-65** signing each audit entry, 3,309-byte signatures, about 48 ms each

The audit log is hash-chained: each entry carries the hash of the one before it, and
verification recomputes the chain and checks every signature. Editing a single field
breaks it, which `python security/security.py` demonstrates by tampering with an entry and
failing verification. **The chain holds no clinical content** — only hashes, a role, an
action name and a pseudonymous subject id — so no medical fact can be recovered from it.

Four roles with distinct rights, enforced on the server, not in the interface:

| role | may |
| --- | --- |
| patient | give consent, read their own estimate |
| nurse | read estimates, quality, change scenario |
| doctor | the above plus raw signals, export, read audit |
| admin | read and verify audit, manage keys, read quality |

Switch the role in the dashboard and watch panels disappear. An admin may verify the
chain but may not read a pain estimate; a patient may not change the scenario and the
server says so.

Aligned with Algerian **Law No. 18-07**: a session refuses to start until consent is
recorded for the subject, only derived window features are processed (no name, no address,
no raw video or audio is persisted), subjects are pseudonymous as VP-nn, and every access
is signed and chained.

## Running it

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python backend/server.py
```

That one command is enough. If the dataset or the learned weights are missing it
generates and trains them first, which takes about ten seconds, and then serves the
dashboard, the API and the WebSocket. It prints the address to open, normally
<http://127.0.0.1:8000>; if that port is taken it moves to the next free one and says so.

To run the pipeline by hand:

```bash
.venv/bin/python ai/simulate.py      # writes dataset/dataset.csv, 5,760 windows
.venv/bin/python ai/train.py         # writes config/learned_weights.json and dataset/results.json
.venv/bin/python security/security.py  # crypto, RBAC, consent and tamper self-check
```

### The dashboard

Three stream gauges with quality lamps, the fused gauge, a confidence meter, weight bars
showing what each layer did to the weights, the confounder alert, a timeline of the
estimate against the self-report and the simulated truth, and the offline evaluation.
The scenario buttons drive a live patient: rest, pain at any level 1-10, exercise,
anxiety, sedated, and sensor failure, which cycles through losing stream A, then B, then
C, then all three so you can watch the weights collapse and the system refuse to answer.

### Camera

Stream C is simulated by default. To read a real webcam instead:

```bash
PAINSCORE_CAMERA=0 .venv/bin/python backend/server.py
```

The action units then come from MediaPipe's face landmarker blendshapes, which map onto
the requested units directly: `browDown` to AU4, `cheekSquint` to AU6, `eyeSquint` to AU7,
`noseSneer` to AU9, `mouthUpperUp` to AU10 and `eyeBlink` to AU43. Smiles come from
`mouthSmile` and speech from the variance of `jawOpen`. The green channel of a forehead
patch feeds a 12-second rPPG estimate, band-limited to 0.7-3.0 Hz and rejected when the
spectral peak is not at least three times the band mean. Lighting comes from frame
brightness, and a frame with no face sets the occlusion flag, which attenuates the stream
through layer 4 exactly as a covered face should.

This needs `backend/face_landmarker.task`, the 3.6 MB model bundle from Google's
mediapipe-models storage. Point `PAINSCORE_FACE_MODEL` elsewhere if you keep it somewhere
else. Without the model the camera still supplies lighting and the action units stay
simulated; without a camera the whole stream stays simulated. Each fallback says which
one it took, in the dashboard.

### Patch telemetry over MQTT

The server subscribes to `painscore/patch/+/telemetry` and publishes each estimate to
`painscore/estimate/<subject>`. With no broker reachable it says so and keeps simulating.

```bash
PAINSCORE_MQTT_HOST=localhost .venv/bin/python backend/server.py
mosquitto_pub -t painscore/patch/wrist-01/telemetry \
  -m '{"heart_rate": 118, "gsr_tonic_us": 9.4, "respiration_rate": 26, "motion_index": 0.71}'
```

Accepted fields are `heart_rate`, `hrv_rmssd`, `gsr_tonic_us`, `skin_temp_c`,
`respiration_rate`, `motion_index` and `quality`. Anything else is ignored. The deltas
against the patient's baseline and the Pain Stress Index are recomputed from whatever
arrives.

### Settings

| variable | default | meaning |
| --- | --- | --- |
| `PAINSCORE_HOST` | 127.0.0.1 | bind address |
| `PAINSCORE_PORT` | 8000 | port, moves to the next free one if taken |
| `PAINSCORE_INTERVAL` | 1.0 | seconds between windows |
| `PAINSCORE_CAMERA` | -1 | camera index, -1 to simulate stream C |
| `PAINSCORE_FACE_MODEL` | backend/face_landmarker.task | landmarker bundle |
| `PAINSCORE_MQTT_HOST` | localhost | broker |
| `PAINSCORE_MQTT_PORT` | 1883 | broker port |

### API

| endpoint | returns |
| --- | --- |
| `GET /api/scenarios` | scenarios, contexts, layer mixing ratios |
| `GET /api/results` | the offline evaluation |
| `GET /api/security` | provider, algorithms, chain state, compliance notes |
| `GET /api/audit?role=doctor&limit=20` | audit entries, 403 for roles without the right |
| `POST /api/verify?role=admin` | recomputes and verifies the chain |
| `WS /ws` | one estimate per second, with scenario and role control |

## Layout

```
dataset/   dataset.csv, dataset_card.md, results.json
ai/        simulate.py, fusion.py, train.py, trained.joblib
security/  security.py
backend/   server.py, face_landmarker.task
frontend/  index.html, style.css, app.js
config/    weights.json, learned_weights.json
```

## What it does not do

Every number comes from a simulation. The generator is a set of response curves with
noise, not physiology: there is no simulated EEG waveform behind the band powers, no
rendered face behind the action units and no audio behind the voice features. Windows
within a patient are independent, so there is no drift, no carry-over and nothing for a
temporal model to learn. `dataset/dataset_card.md` sets out the limits in full.

Nothing here has been validated against a human being, and the accuracy figures describe
the simulation and nothing else.
