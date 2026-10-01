# EEG & EMG Pain Analysis

Records cortical and muscle activity, measures signal quality, extracts standard spectral
and amplitude features, and offers those features to a pain model.

**The model this ships with reads skin conductance and nothing else.** It is trained on the
experimental half of the PainMonit database and it is not an EEG or EMG model: that corpus
samples every channel at 250 Hz, which is below the rate these EMG channels need, so no
muscle feature is in it. What it predicts is that corpus's own continuous visual analogue
rating, 0 to 100 — not a 0-10 score — and the scale is reported beside every number it
produces. See [Model](#model) below for how it was fitted and what its error is.

Where no model is registered, or where a recording derives none of the features the
registered one needs, the report says so instead of producing a figure:

> AI model unavailable — signal recording and feature analysis completed, but pain
> estimation requires a trained model.

`/api/signals/reference` reports `model_available` before a recording is even started, so
the interface does not promise an estimate it cannot produce and only discover that when the
report comes back empty.

---

## Electrical safety — read this first

**Never connect a person to a circuit that has any path to mains power.** A fault in a
mains-powered device can put line voltage onto an electrode attached to someone's scalp or
chest. This is the one failure in this document that injures people.

- Run the amplifier and the host from **battery power**, or through a **medical-grade
  isolated** USB barrier. A laptop on a charger is mains-connected.
- Use an amplifier with isolation designed in. The boards named below have it; a
  breadboard instrumentation amplifier does not.
- Nothing here is a certified medical device. It is research instrumentation. Do not use it
  for diagnosis, monitoring a patient whose care depends on it, or anything in an
  operating theatre.

**Do not wire EEG electrodes to ESP32 or Arduino pins.** Scalp EEG is 10–100 µV. A bare
microcontroller ADC resolves about 800 µV per count at 12-bit over 3.3 V, so the entire EEG
sits inside one count — you would be sampling noise with a 50 Hz hum on top. EEG needs a
differential instrumentation amplifier with a gain around 24,000, a 24-bit ADC, and a driven
reference. That is what the boards below contain, and it is why they are not optional.

---

## Hardware

### EEG — pick one

| Board | Channels | Rate | Notes |
| --- | --- | --- | --- |
| **OpenBCI Cyton** | 8 | 250 Hz | ADS1299, battery powered, well documented. The straightforward choice |
| OpenBCI Ganglion | 4 | 200 Hz | Cheaper, fewer channels, Bluetooth |
| ADS1299 breakout + MCU | 8 | configurable | Cheapest, and you are responsible for the isolation |
| g.tec / Brain Products | 8+ | 500 Hz+ | Research grade, research prices |

### EMG — pick one

| Module | Notes |
| --- | --- |
| **Olimex SHIELD-EKG-EMG** | Instrumentation amplifier with the right band-pass. Stacks on an Arduino, but sample it through an isolated path |
| MyoWare 2.0 Muscle Sensor | Outputs a rectified envelope by default. Take the **RAW** output — the envelope has already thrown away the spectral content the features need |
| Bitalino (r)evolution | EMG plus a PPG sensor, a GSR pair and a respiration belt in one isolated, battery-powered unit |
| OpenBCI Cyton | Can take surface EMG on spare channels, but at 250 Hz it undersamples EMG — see the rate table |

### Optional

- **PPG**: a fingertip or earlobe pulse sensor, or a Bitalino PPG module. Reported as a
  pulse rate and the time-domain variability figures (SDNN, RMSSD, pNN50).
- **GSR**: two electrodes on the volar surface of the index and middle fingers, through any
  constant-voltage skin conductance module. Reported as a level in microsiemens, its drift,
  and the rate of spontaneous responses.
- **Respiration**: a piezo or strain chest belt. Reported as a rate only — it is a relative
  excursion, not a volume.

Blood pressure is **not** a channel here. A cuff gives a pair of numbers a few times a
visit, not a sampled trace, so systolic and diastolic belong in the assessment's vitals
(`sbp`, `dbp`), where the reference ranges and the plausibility checks already live.

### Electrode placement

EEG, using the 10–20 system, with the two derivations this platform defines. Both are on
the midline: nothing in the feature set reads a difference between the hemispheres, so a
left/right pair would cost two more electrodes and two more chances to apply one badly in
exchange for a number no feature uses.

| Channel | Site |
| --- | --- |
| `EEG_FPZ` | Frontal midline, above the bridge of the nose |
| `EEG_CZ` | Vertex, midway between the ears over the sensorimotor strip |

Plus a **reference** (A1/A2 earlobe or mastoid) and a **bias/ground** — the amplifier needs
both or every channel sees the same common-mode noise.

Skin preparation decides whether any of this works. Clean with alcohol, abrade lightly, use
conductive gel, and keep impedance under about 10 kΩ. A dry electrode on unprepared skin
gives a trace the quality checks will mark `UNUSABLE`, and they will be right.

Surface EMG, for the two channels defined here:

| Channel | Placement |
| --- | --- |
| `EMG_TRAPEZIUS_L` / `_R` | Two electrodes 2 cm apart along the upper trapezius fibres, with a reference over a bony prominence (acromion or spine of C7) |

### Sampling rates

| Modality | Minimum | Recommended | Why |
| --- | --- | --- | --- |
| EEG | 128 Hz | 250–512 Hz | The gamma band reaches 45 Hz, so Nyquist needs 90 Hz plus headroom |
| EMG | 500 Hz | 1000–2000 Hz | Surface EMG power extends past 250 Hz; at 250 Hz you alias most of it |
| PPG | 100 Hz | 250 Hz | The pulse itself needs far less; the beat-to-beat intervals are what need the resolution. At 100 Hz each interval carries 10 ms of timing error, already a fifth of a normal RMSSD |
| GSR | 4 Hz | 16–32 Hz | A skin conductance response rises over about a second |
| Respiration | 10 Hz | 25 Hz | Breathing is under 0.7 Hz |

A channel sampled below its minimum is flagged, not silently accepted. Running a single
amplifier at 250 Hz for both EEG and EMG works for EEG and undersamples EMG; the EMG median
frequency will be wrong and the flag tells you so.

---

## Connecting it to the platform

There are two ways in, and the difference matters.

**Server-side acquisition.** The backend opens the device itself and an acquisition thread
reads from it. Three adapters, one per protocol:

| Adapter | Protocol | Transport |
| --- | --- | --- |
| `openbci_cyton` | OpenBCI's published 33-byte serial frames, 24-bit signed, documented scale factor | USB serial, 115200 baud |
| `serial_gateway` | Newline-delimited JSON **defined by this platform** — see below | USB serial |
| `ble_gateway` | The same JSON over a Nordic UART characteristic | BLE (needs `bleak`) |

`GET /api/signals/devices` lists what is currently visible, with each adapter's protocol
stated. A port that looks like a Cyton from its USB descriptor is reported as a *candidate*
with `confirmed: false`; only a successful open confirms it. An empty list is the honest
answer and the interface shows "Device not connected" on it.

To record from one, name it at start:

```bash
curl -X POST localhost:8000/api/signals/recordings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{
    "patient_id": "<uuid>",
    "channels": ["EEG_FPZ","EEG_CZ","EMG_TRAPEZIUS_L"],
    "channel_rates": {"EEG_FPZ": 250, "EEG_CZ": 250, "EMG_TRAPEZIUS_L": 1000},
    "adapter": "openbci_cyton",
    "device_identifier": "/dev/ttyUSB0"
  }'
```

**Client-relayed acquisition.** Whatever already owns the device — the OpenBCI GUI, a
BrainFlow script, a browser over Web Serial — posts sample blocks instead. Leave `adapter`
unset. This is the path to use for a board no adapter covers, and for a device attached to a
machine other than the server.

### The gateway protocol

There is no standard protocol for an ESP32 or Arduino front end, so this platform defines
one. One JSON object per line:

```json
{"i": 1024, "ch": {"EEG_FPZ": 12.5, "EMG_TRAPEZIUS_L": -34.1}}
```

`i` is the device's own sample index and must increase by one per sample, which is what makes
a dropped sample detectable. `ch` maps channel codes to values **already in the channel's
declared unit** — microvolts for EEG and EMG. Scaling is the firmware's job: the adapter will
not guess a gain, because a wrong guess produces plausible numbers in the wrong units.

A line that is not valid JSON, or lacks `i` or `ch`, is counted as an invalid packet and
skipped. A channel absent from one line becomes a gap, never a zero.

An ESP32 is a *transport*. It is not an isolated biomedical amplifier, and this protocol
carries no safety guarantee — see the safety section above.

```python
# A client-relayed recording using BrainFlow, which supports Cyton, Ganglion, Bitalino and
# others. For a Cyton attached to the server itself, the `openbci_cyton` adapter does this
# without a relay script.
import time, requests
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds

API = "http://localhost:8000"
TOKEN = "<access token from POST /api/auth/login>"
HEAD = {"Authorization": f"Bearer {TOKEN}"}

# The platform channel codes, in the order your board's channels map onto them.
MAPPING = {0: "EEG_FPZ", 1: "EEG_CZ", 2: "EMG_TRAPEZIUS_L", 3: "EMG_TRAPEZIUS_R", 4: "PPG_FINGER"}

board = BoardShim(BoardIds.CYTON_BOARD, BrainFlowInputParams())
board.prepare_session()
rate = BoardShim.get_sampling_rate(BoardIds.CYTON_BOARD)
eeg = BoardShim.get_eeg_channels(BoardIds.CYTON_BOARD)

recording = requests.post(f"{API}/api/signals/recordings", headers=HEAD, json={
    "patient_id": "<patient uuid>",
    "channels": list(MAPPING.values()),
    "sample_rate_hz": float(rate),
    "source": "HARDWARE",
    "device_label": "OpenBCI Cyton",
}).json()

board.start_stream()
try:
    while True:                       # until the operator stops it
        time.sleep(1.0)
        data = board.get_board_data()  # drains the buffer
        if data.shape[1] == 0:
            continue
        block = {
            code: data[eeg[index]].tolist()
            for index, code in MAPPING.items()
            if index < len(eeg)
        }
        requests.post(
            f"{API}/api/signals/recordings/{recording['id']}/samples",
            headers=HEAD, json={"samples": block},
        )
finally:
    board.stop_stream(); board.release_session()

# Stop saves and validates. Analysis is a separate call.
saved = requests.post(
    f"{API}/api/signals/recordings/{recording['id']}/stop", headers=HEAD
).json()
print(saved["state"], saved["validation"]["intact"], [f["name"] for f in saved["files"]])

report = requests.post(
    f"{API}/api/signals/recordings/{recording['id']}/analyze",
    headers=HEAD, json={"reported_nrs": 6},
).json()
print(report["quality_verdict"], report["analyses"][0]["summary"])
```

### Sampling rates are per channel

`channel_rates` is the authoritative record and a single `sample_rate_hz` is a convenience
derived from it. EEG at 250 Hz beside surface EMG at 1 kHz is the normal case, not an
exception, and quality and features are computed **per rate group**: no channel is resampled
onto another's clock, because doing so would alter the signal the features describe. An EMG
median frequency computed under an EEG rate assumption lands in the wrong place entirely.

Values are in the channel's declared unit — microvolts for EEG and EMG, microsiemens for
GSR, arbitrary units for the PPG and the respiration belt.
BrainFlow returns microvolts for EEG by default; if your source returns raw ADC counts,
convert before posting or the saturation check will be meaningless.

Samples are written to the session files **as they arrive**, not held until stop. An
interrupted recording therefore keeps everything written up to that moment; what it lacks is
the metadata and quality report, which is how an interrupted session is recognised. The open
file handle lives in the serving process, so **stream and stop against the same process** —
behind more than one worker, pin the session or run a single worker for acquisition.

---

## Testing the workflow

### Without hardware

The simulator is the supported way to exercise the whole path. Everything it produces is
stored and displayed as `SIMULATION` and can never merge with hardware data — `source` is a
non-null column with no default, so a row cannot exist without saying which it is.

In the interface: **EEG & EMG** in the sidebar → paste a patient UUID → leave the toggle on
**SIMULATION MODE** → **Start Analysis** → **Stop & Analyze**.

By API, in one call:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.org","password":"..."}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

REC=$(curl -s -X POST localhost:8000/api/signals/recordings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
    "patient_id": "<patient uuid>",
    "channels": ["EEG_FPZ","EEG_CZ","EMG_TRAPEZIUS_L","PPG_FINGER","GSR_PALMAR","RESPIRATION_BELT"],
    "source": "SIMULATION", "simulate_seconds": 30, "simulate_seed": 7
  }' | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')

curl -s -X POST "localhost:8000/api/signals/recordings/$REC/stop" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reported_nrs": 6}' | python3 -m json.tool
```

Reproduce each degraded state deliberately with `simulate_faults`:

| Fault | Reproduces | Expected |
| --- | --- | --- |
| `flatline` | Electrode not connected | `UNUSABLE`, no features for that channel |
| `saturated` | Amplifier driven into its rails | `UNUSABLE`, clipping share reported |
| `mains` | 50 Hz hum swamping the signal | `UNUSABLE`, mains share reported |
| `missing` | Lead dropped out mid-recording | Missing share counted, gap in the trace |

```bash
# A detached central electrode, with the frontal one still good.
... -d '{"..." : "...", "simulate_faults": {"EEG_CZ": "flatline"}}'
```

A fault on a *supporting* channel does not void the session: a slipped respiration belt
costs the respiratory rate and leaves a clean EEG and EMG recording `GOOD`. A detached EEG
does degrade it, because that is what the analysis is of.

### With hardware

1. Electrodes on, skin prepared, amplifier on **battery**.
2. Confirm the device streams in its own software first. If it does not work there, the
   problem is not this platform.
3. Start the relay script above, or **Start Analysis** with the toggle on **REAL HARDWARE**.
4. Watch the live panel: elapsed time counting, sample count rising.
5. **Stop & Analyze**, then read the per-channel quality block in the report before
   anything else. `GOOD` or `ADEQUATE` on the EEG and EMG channels means the features are
   worth reading. `POOR` or `UNUSABLE` means fix the electrodes — the findings name what
   went wrong, and a feature from a bad trace is a number with no referent.

### Automated tests

```bash
cd backend && source .venv/bin/activate
python -m pytest tests/test_signals_processing.py tests/test_signals_api.py \
  tests/test_signal_devices.py -q
```

125 tests across three files:

- **`test_signals_processing.py`** checks the arithmetic against signals constructed in the
  test — a 10 Hz sine must land in the alpha band, a 1.2 Hz pulse must read 72 bpm — rather than
  only that a number came back.
- **`test_signal_devices.py`** drives the adapters with exact bytes through a fake serial
  port: Cyton frames built from the published format, two's-complement decoding at the rails,
  garbage before a frame, a bad stop byte, a truncated trailing frame, a dropped-sample index
  gap, a wrapping counter, disconnection with and without reconnection, and every invalid JSON
  shape the gateway can receive.
- **`test_signals_api.py`** covers the workflow, per-modality rates, validation findings,
  re-analysis, storage failures at start and mid-block, and device errors.

No hardware is needed for any of it. A protocol parser is testable by feeding it the frames
the protocol specifies, which is the only way to know the scale factor and the
two's-complement handling are right without an amplifier on the bench.

---

## Where recordings are saved

One directory per session, under one directory per participant, below
`SIGNAL_STORE_PATH`:

```
recordings/<participant>/<session>/
    eeg.csv               sample_index, timestamp_ns, one column per EEG channel
    emg.csv               the same, at the EMG rate
    other.csv             pulse, conductance and respiration, where present
    metadata.json         device, rates, channels, units, consent, provenance
    signal_quality.json   written when the recording is analysed
```

The participant directory is the patient's internal id — no name, and deliberately not the
MRN-shaped `code`, so a directory listing is not a patient index.

One file per modality because the rates differ: channels on different clocks cannot share a
row without resampling or padding, and either done silently would misrepresent the data. Each
file carries its own sample index and its own timestamps.

Timestamps are **integer nanoseconds**. An epoch time is about 1.7e9, where float64 resolves
roughly 240 ns, so adding a 0.5 ms sample interval to it loses part of the interval and a
2 kHz recording comes back visibly uneven. This is the same reason `datetime64[ns]` is
defined that way.

A gap is an empty cell, never a zero. A dropped lead must not be indistinguishable from a
measured zero.

CSV rather than HDF5: ten minutes of 8-channel EEG at 250 Hz is about 12 MB, and a reviewer
being able to open the file without a library is worth more than the space. `app/signals/storage.py`
is the one module that would change if rates or durations grew by an order of magnitude.

## Recording states

| State | Meaning |
| --- | --- |
| `RECORDING` | Open and acquiring, or accepting relayed blocks |
| `PROCESSING` | Stop in progress: flushing files, writing metadata |
| `SAVED` | Written and validated, waiting for Analyze Recording |
| `ANALYSED` | Analysed, with a report. Re-analysable |
| `DISCARDED` | Stopped with no samples, abandoned, or discarded by the operator |
| `FAILED` | The files could not be written; the error is on the row |

**Stop and Analyze are separate** so a session can be recorded at the bedside and analysed
later, and so a failed analysis does not put the recording in doubt. Analysis is re-runnable:
analysing again adds an analysis rather than replacing the first, which is what lets a later
model be applied to an existing recording without re-recording the patient.

## Validation versus signal quality

Two different questions, answered separately.

**Validation** is about the files: is every declared channel present, do the row counts match
the metadata, are the digests reproducible, how many samples did the device number that never
arrived. Run at stop, stored in `validation`.

**Signal quality** is about whether the trace is readable: electrode attached, amplifier not
clipping, mains hum not swamping it. Run at analysis, stored in `quality` and in
`signal_quality.json`.

A recording can be perfectly intact and completely unusable — that is a detached electrode,
and both facts are recorded.

## How to verify the signals are real

Worth being able to answer, because an animated chart and a recording look identical on
screen.

1. **Check the provenance field.** `source` is `HARDWARE` or `SIMULATION`, it is NOT NULL with
   no default, and it is on the recording row, the API response, the history table and
   `metadata.json`. A simulated session cannot exist without saying so.
2. **Read the raw CSV.** `eeg.csv` holds the actual samples with their indices and timestamps.
   A simulator's output and an amplifier's look different: real EEG has a 1/f background, mains
   hum at 50 or 60 Hz unless notched, and electrode drift.
3. **Check the device counters.** `dropped_samples`, `invalid_packets` and `reconnects` come
   from the device's own sample index and frame validity. A simulated recording has all three
   at zero; a real USB session over several minutes almost never does.
4. **Unplug an electrode mid-recording.** The quality report should mark that channel
   `UNUSABLE` with "the electrode is not connected". Nothing simulated responds to that.
5. **Compare the digest.** `sha256` is taken over the written files at stop and recomputed at
   validation. A mismatch means the files changed after the recording.
6. **Look at the sample count against the duration.** `samples / rate` should equal
   `duration_seconds`. A fabricated recording has no reason for those to agree.

A recording left open for 30 minutes is closed by `service.sweep_stale`, so the history has
no rows stuck at `RECORDING`.

---

## What is measured, and what it is not

Features are standard spectral and amplitude measures:

- **EEG**: absolute and relative power in delta, theta, alpha, beta and gamma; alpha/beta
  and theta/alpha ratios; 95% spectral edge; RMS.
- **EMG**: RMS, mean absolute value, waveform length, zero crossings and slope sign changes
  per second, mean and median frequency, in-band power — all after a 20–250 Hz band-pass,
  because unfiltered surface EMG carries a movement baseline that dominates RMS.
- **PPG**: pulse rate, mean beat-to-beat interval, SDNN, RMSSD and pNN50 — all from the
  beats found in the waveform, so the rate and the variability arrive together or not at
  all. Over a recording this short they come out smaller than the five-minute figures they
  would be compared with, and the analysis says so beside them.
- **GSR**: the tonic level in microsiemens, its spread, its range, its drift per minute, and
  the rate of non-specific skin conductance responses — non-specific because this module is
  given no stimulus to relate them to.
- **Respiration**: a rate only.

**None of these is a pain measure.** They move with arousal, attention, movement, electrode
placement and skin temperature as well as with pain. The platform reports them as signal
measurements and makes no claim about which part of a number is which. That is most obvious
on the autonomic channels: skin conductance is a measure of arousal, and arousal is not
pain.

Three rules are enforced in the schema rather than by convention:

- **An unusable channel yields no features**, not zeros. A feature from a flat trace is a
  number with no referent, and the absence is recorded per channel with the reason.
- **The patient's own score is stored apart and is never an input.** `reported_nrs` sits on
  the analysis beside the estimate; a test asserts no feature name contains it.
- **A score is never invented.** With no model, `pain_score` is null — not zero — and
  `estimate_available` is false with the message above.
- **A score never travels without its scale.** `scale` sits beside `pain_score` on the
  analysis row, holding the scale in the words of whoever published the labels the model
  was trained against. `pain_category` is null unless that scale is the platform's own
  0-10 one, whose bands are the only ones defined — reading 30 out of 100 through them
  would report moderate pain as severe.

## Model

Fitted by `app.signals.training` on the PainMonit database, which is two databases
published together: an experimental half of 52 volunteers under contact heat calibrated to
each person, and a clinical half of 49 physiotherapy patients rating their pain aloud
during treatment. Both are synchronised at 250 Hz.

```bash
python -m backend.cli train-signal-pain --dataset /path/to/painmonit
python -m backend.cli train-signal-pain --dataset /path/to/painmonit --half clinical
```

`--dataset` is the directory holding `PMED.zip` and `PMCD.zip`, or their extracted trees.
The archives are read in place and nothing is copied out of them: the database comes under
a usage agreement that permits academic research only and forbids redistribution, so it is
never held in this repository. Any publication reporting on its use must cite Gouverneur,
Badura, Li et al., *An Experimental and Clinical Physiological Signal Dataset for Automated
Pain Recognition*, Sci Data 11, 1051 (2024) — the citation is stored on the model row.

**How it is read.** Through `app.signals.quality` and `app.signals.features`, the same two
functions that measure a recording made on a ward, rather than through an extractor of its
own. A model fitted on numbers computed somewhere else would be handed different numbers at
the bedside under the same names and nothing would report the difference.

**What maps onto what.** The corpus's RespiBAN skin conductance becomes `GSR_PALMAR` — it
sits at 8-25 µS against the Empatica wrist trace's 0.6-11, and palmar sites conduct better,
so the higher pair is the more palmar. It is already in microsiemens and is not rescaled.
Blood volume pulse and respiration become `PPG_FINGER` and `RESPIRATION_BELT`, each
multiplied by one fixed factor that puts the corpus's median peak where this platform's
amplifier convention puts it; every feature derived from either is a timing or a rate, so
the factor reaches the quality check and never a feature value. EMG and ECG are not read,
for the sampling rate reason above.

**How it is validated.** Grouped by person, always. Every figure below is a cross-validated
prediction from a model that never saw that person. Resting skin conductance differs
severalfold between people and barely at all within one, so a split taken across rows would
score well by recognising skin rather than pain.

**What was chosen.** Three candidates — gradient boosting, random forest, ridge — crossed
with three channel sets, nine combinations, lowest held-out error wins. Adding a channel
that earns nothing is not free: a model can only be offered a recording that derives every
feature it declares.

| half | windows | people | selected | error | mean baseline | r |
| --- | --- | --- | --- | --- | --- | --- |
| experimental | 4,159 | 52 | random forest, 5 skin conductance features | **15.14** on VAS 0-100 | 24.11 | 0.66 |
| clinical | 1,268 | 49 | ridge, 5 skin conductance features | 2.16 on NRS 0-10 | 2.08 | −0.16 |

The experimental model also separates a rest window from the hottest calibrated stimulus at
AUC 0.94, and from any stimulus at AUC 0.72 — the lowest steps sit near a volunteer's own
threshold and were often rated at nothing, which is why the second figure is the honest one.
Error rises with intensity: 9.6 on rest windows, 32.7 on the top step.

**The clinical half is registered inactive.** It does not beat predicting the mean. Adding
the pulse and respiration channels does not change that, and nor does correcting each
window against the patient's own run-up recording, which the database ships and which was
tried for exactly this. Patients are asked every seven seconds on average, so twenty-second
windows overlap heavily and the model sees far fewer independent moments than it has rows.
That is a finding about this half of the corpus and the record of it is kept; what it is not
is a model to serve.

**No interval is fitted.** A quantile pair would come off the same overlapping windows as
the point estimate. The cross-validated error is reported instead and is the one error
figure this model has.

Pulled in the other direction: pointing the trainer at a corpus whose labels *are* a 0-10
numeric rating scale, and which beats its mean, gives a model the platform bands and reads
like its own. `app/signals/inference.py` checks the registry name *and* the feature schema
version, because a model trained on an older feature set would accept the right number of
columns and mean something different by them.
