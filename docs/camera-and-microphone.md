# Camera and microphone

Records a short clip of a patient, measures what their eyes, face and voice are doing, and
offers the acoustic part to a model trained on real human recordings.

This is the platform's behavioural observation channel, and that framing is the reason it
exists. The platform already knows which patients cannot be asked for a number — a newborn,
someone with dementia, someone intubated — and for exactly those patients the reference
scale is observational: NIPS, FLACC, PAINAD, CPOT. Every one of those scales has a facial
item and most have a vocal one, scored by a clinician looking and listening. Until this
channel, the platform declared both as signals it did not measure.

**None of it is a pain measure.** A pupil widens with pain, and with fear, a dark room,
withdrawal and surprise; opioids shrink it. A blink rate rises with distress and with dry
eyes, and falls with concentration and with sedation. Every figure here carries the sentence
that says so, in the interface and in the API.

---

## What the patient is asked to do

> Ask the patient to look at the camera with their eyes open and to speak or read aloud for
> the length of the recording.

The eye measures are taken only from frames where **both eyes are found open**. That is a
gate, not a weighting: below a floor of such frames the eye modality is refused outright
rather than averaged over a handful. A sleeping or sedated patient therefore gets no eye
reading, which is the correct answer — what there is to see is the closure itself, and that
is counted separately and does not need the eyes to be open.

The instruction is on screen while the camera is live, and it is stored with the
observation, so a reading can be judged against the instruction it was taken under.

---

## How the eyes are measured

Everything comes from one segmentation: the iris, which in a grayscale image of an eye is
the dark compact region in the middle of the opening. Finding it gives three things at once.

**A ruler.** The horizontal visible iris diameter is close to 11.7 mm in every adult eye and
barely changes with refractive error, which makes it the one thing in a webcam image whose
real size is known. The pixels-to-millimetres factor falls out of the segmentation itself,
so nothing has to be calibrated and the patient can sit where they like. Every millimetre
figure is scaled by it, and without an iris there is no millimetre figure at all.

**The aperture.** In an open adult eye the lids cross the iris top and bottom, so the
visible iris is a disc with two chords cut off it. Its height over its width is a direct
reading of how far the lids have closed, and it is scale-free by construction. It saturates
in the rare case of a lid retracted clear of the iris — a startled stare — which is reported
as a ceiling rather than extrapolated past.

**The pupil.** Inside the iris, the pupil is darker again. The threshold is found within the
iris alone rather than across the image, which is what makes it survive a room where one
side of the face is brighter than the other.

### Two decisions that decide whether any of it means anything

**Thresholds are found by Otsu's method, never as a share of the darkest pixels.** Taking a
fixed share of the iris as the pupil hands that share straight back as the answer whatever
the pupil is doing — a measurement that looks entirely plausible and measures nothing.
Taking a fixed share of the window as the iris makes the aperture depend on how much of the
window the lids have covered.

For the iris the method is run for **three** classes rather than two. An eye window holds
three populations — the iris around 60 of 255, the lid skin around 160, the sclera above
200 — and the widest gap in that histogram is between skin and sclera, so an ordinary
two-class threshold splits there and calls the lids dark. Running it twice is not a fix
either: where the first split already isolated the iris, the second goes on to separate the
pupil from it and the ruler collapses onto the pupil. Both thresholds are searched for
together and the lower one is taken.

**Where the eyes are is calibrated, not assumed.** The library's eye cascade is trained on
open eyes, so it stops firing the moment the patient blinks — using it frame by frame would
throw away every frame of the one behaviour most worth counting. Fixed proportions of the
face box do not work either, because the dark round thing nearest the middle of a generous
eye window is sometimes the eyebrow, and a clip of a sleeping patient then comes back with
two open eyes and a plausible pupil measured off their eyebrows.

So a first pass runs the eye cascade over a sample of frames and records, relative to the
face box, where it found the eyes **and how wide this patient's iris is**. The measuring
pass uses both on every frame, including the frames where the eyes are shut: the width is
what separates a closed eye from a brow, since a brow is two or three times as wide as the
iris above it. Where the cascade never fires — a patient who squints throughout, which is
what it declines to fire on and also what there is to measure — the anatomical iris width is
used with a wider tolerance, and the observation says so.

### What comes back

| Measure | What it is |
| --- | --- |
| Frames with both eyes open | The gate. Everything below is averaged over these |
| Eye aperture | Visible iris height over its width |
| Orbital tightening | How far the aperture has narrowed from this patient's resting opening. AU6 and AU7 |
| Blink rate, mean blink duration | Spontaneous blinks per minute, and how long each lasted |
| Time with the eyes squeezed shut | Closures too long to be a blink. AU43, kept apart so one does not corrupt the other |
| Pupil diameter, pupil against iris | Scaled from the iris. An arousal measure, not a pain measure |
| Pupillary unrest | Spread of the diameter across the window |
| Difference between the pupils | Beyond about a millimetre this is a neurological finding to look at |
| Gaze movement | How far the pupil centre wandered inside the opening |
| Difference between the two eyes | A persistent difference is a facial nerve finding, not a pain finding |

The face box also yields brow lowering (AU4), mouth opening, head movement and the share of
the window spent facing away.

**The composite is a partial score and is not called PSPI.** Three of the four facial
actions the Prkachin and Solomon pain intensity score is built from are measurable from a
face box: orbital tightening, sustained closure, brow lowering. The fourth — the levator
contraction that wrinkles the nose and raises the upper lip — is not, and is not guessed at.

---

## How the voice is measured

Pitch by autocorrelation, with the peak interpolated across its neighbours. The
interpolation is not a nicety: jitter is a difference between consecutive pitch periods of a
percent or two, and at 22 kHz a period of 200 Hz is 110 samples, so rounding the peak to the
nearest sample puts a floor of nearly 1% on a measurement whose interesting range starts at
0.5%.

The correlation is normalised over the two stretches that actually overlap at each lag
rather than over the whole frame. Dividing by the whole frame costs a perfectly periodic
signal about a tenth of its score at 150 Hz and a third at 60 Hz — a pitch-dependent penalty
that would land straight in the harmonics-to-noise figure read off it. That normalisation
makes a different correction necessary: a perfectly periodic signal then scores 1.0 at one
period and 1.0 again at two, so the shortest lag that explains the signal about as well as
the best one is preferred, which is the octave correction.

**Jitter and shimmer are measured between glottal periods, not between analysis frames.**
Those are the quantities the clinical literature names. Taking the difference between pitch
estimates ten milliseconds apart would be a different and much smoother thing. Within each
voiced stretch the individual periods are marked on the waveform and the perturbation is
taken across them.

Also measured: harmonics-to-noise, loudness, the voiced and silent shares, a syllable rate
from the loudness envelope, the share of voiced time spent on sustained non-speech sound —
a moan or a cry, which PAINAD and CPOT score by hand — and the spectral descriptors.
Nothing here recognises a word.

---

## The role of the resting observation

Orbital tightening and brow lowering are **changes from a resting value** and cannot be
computed without one. The best reference is a short clip of the same patient settled, marked
`at_rest`, which is stored on their baseline beside their resting vitals. Failing that, the
widest moment inside the same window is used — a real within-recording comparison rather
than a population average — and the limitation is plain: a patient who squinted from the
first frame to the last has no wide moment, so the index reads low.

The source is recorded alongside every such value, so a reader can see which they have.

This is also why a pitch of 180 Hz or a pupil of 5 mm means nothing on its own. The first is
low for one voice and high for another; the second is wide for one person and ordinary for
the next. The change from the same patient at rest is the figure that transfers, and it is
what the model is given.

---

## The two models

### The clinical estimator

The behavioural measures are features of the platform's main pain model, alongside the
examination and the vitals — feature schema version 4. They are weighed against everything
else rather than read on their own, and a measure the clip did not support reaches the model
as missing rather than as a zero, so "no clip was recorded" and "the eyes were never open"
stay distinct from "the eyes were barely open".

That model is trained on synthetic cases, and the behaviour in them is generated with two
properties that matter more than the correlation itself:

- **Expressiveness varies several-fold between patients.** How much of their pain a person
  shows in the face and the voice differs enormously at the same reported intensity, and
  older adults and patients with dementia show less of it. Generating without that produces
  a dataset in which a face predicts pain better than it does in any published cohort.
- **The confounders break the relationship in both directions.** Anxiety and fear widen a
  pupil and raise a blink rate with no pain behind them; sedation and opioids flatten a
  grimace that pain is producing. The first is how a behavioural channel produces a false
  positive, the second is how it produces a false negative on the patient least able to say
  so, and a model that has never seen either learns that a calm face means no pain.

### The voice model

This is the one model in the platform trained on human pain data rather than on synthetic
cases. The corpus is PainSpeech-4: 779 utterances from 194 speakers, each labelled on a
four-level scale by the experiment that elicited it, acquired and normalised by the
platform's dataset pipeline.

Speaker-grouped cross-validation throughout. Every speaker contributes four utterances, one
per level, so a random split lets the model score well by recognising the voice rather than
the pain. Every figure comes from speakers it never heard, which is also why the scores are
modest:

| | |
| --- | --- |
| Error | **0.65 levels**, against **1.00** for predicting the mean |
| Within one level | 93% |
| Exact level | 46% |
| Speakers | 194, five folds |

It is fitted on thirteen features — the cepstral means — and not on the hundred and twenty
the corpus ships. The rest are dropped because their meaning is not recoverable: the file's
own `_std` columns contain negative values, so whatever they hold is not a standard
deviation, and a model fitted on a column whose definition is unknown cannot be fed
correctly at the bedside.

**It predicts a level, never a score out of ten.** The corpus documents four ordinal classes
and publishes no mapping onto a 0-10 scale. Inventing one would manufacture precision the
data does not have. The level is reported beside the clinical estimate, not inside it, with
three limitations attached to every answer:

- the level is on the corpus's four-point scale, and no mapping onto 0-10 is published;
- the corpus publishes coefficients rather than audio, so it cannot be confirmed that the
  coefficients measured here are identical to the ones it was trained on — the extraction
  geometry is matched to the library defaults its column naming points at, which is an
  inference about how it was produced and not a fact it states;
- it is elicited pain in healthy volunteers speaking Arabic, and whether that acoustic
  change is the change a patient in a ward produces has not been established.

---

## Quality, and what is refused

Judged per modality, because a clip with a clean face and a useless audio track is an
ordinary thing to record and the facial measures from it are fine. Each verdict names what
failed and carries the figures it was reached on.

| Modality | Refused when |
| --- | --- |
| Face | A front-facing view in under a quarter of the frames; out of focus; badly exposed |
| Eye | Both eyes open in under a fifth of the frames, or fewer than twenty such frames |
| Voice | Periodic sound in under 3% of the recording; clipped; the room as loud as the patient |

A measure outside the range a face or a voice produces is dropped with the figure that was
measured, not clamped into the range. A measure with nothing behind it is absent with a
reason, not zero.

---

## Privacy

- **Consent first.** A scope of its own, `CAMERA_AND_MICROPHONE_OBSERVATION`, resolved
  before the file is decoded — not after, and not alongside. A patient who consented to an
  electrode trace has not consented to a recording of their face. The scope is fixed by the
  server, so a client cannot grant consent to something other than what it is asking for.
- **The clip is deleted** once the measures are out of it, unless the clinician asked for it
  to be kept. A kept clip is encrypted under its own data key, bound to the observation that
  owns it, in its own directory so a retention rule can be applied to clips alone. It can be
  deleted afterwards, and the measures survive it.
- **Nothing leaves the deployment.** No face is matched against anything, nothing is
  transcribed, and the stored observation is a table of numbers.

---

## Running it

The analysis needs `ffmpeg` on the path — the audio track of a browser recording is Opus in
a WebM container, and nothing in the Python stack reads that — and `opencv-python-headless`
on the 4.x line, which ships the cascade data the eye localisation runs on. Both are in the
container image.

```
# Train the voice model on the acquired corpus
python -m app.behaviour.training

# Measure a clip
POST /api/behaviour/patients/{id}/observations   clip, at_rest, retain_media
GET  /api/behaviour/reference                    what will be measured, and whether a model exists
GET  /api/behaviour/patients/{id}/resting        this patient's resting observation
PUT  /api/behaviour/patients/{id}/consent        grant or withdraw
DELETE /api/behaviour/observations/{id}/media    delete a kept clip, keep the measures
```

`/api/behaviour/reference` reports whether the voice model exists before a camera is opened,
so the interface does not promise a level it cannot produce and discover that afterwards.
