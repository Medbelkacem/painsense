import asyncio
import json
import socket
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from os import environ
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai import simulate, train
from ai.fusion import ARTIFACT_PATH, INSUFFICIENT, LEARNED_PATH, load
from security.security import PERMISSIONS, SecureSession, permitted

FRONTEND = ROOT / "frontend"
RESULTS_PATH = ROOT / "dataset" / "results.json"

HOST = environ.get("PAINSCORE_HOST", "127.0.0.1")
PORT = int(environ.get("PAINSCORE_PORT", "8000"))
INTERVAL = float(environ.get("PAINSCORE_INTERVAL", "1.0"))
CAMERA_INDEX = int(environ.get("PAINSCORE_CAMERA", "-1"))
MQTT_HOST = environ.get("PAINSCORE_MQTT_HOST", "localhost")
MQTT_PORT = int(environ.get("PAINSCORE_MQTT_PORT", "1883"))

SERVICE_ROLE = "nurse"
SCENARIOS = ("rest", "pain", "exercise", "anxiety", "sedated", "sensor_failure")
FAILURE_CYCLE = ("A", "B", "C", "all")
FAILURE_WINDOWS = 8
TELEMETRY_TOPIC = "painscore/patch/+/telemetry"
ESTIMATE_TOPIC = "painscore/estimate"

PATIENTS = simulate.draw_patients(np.random.default_rng(simulate.SEED))

TELEMETRY_FIELDS = {
    "heart_rate": "b_heart_rate",
    "hrv_rmssd": "b_hrv_rmssd",
    "gsr_tonic_us": "b_gsr_tonic_us",
    "skin_temp_c": "b_skin_temp_c",
    "respiration_rate": "b_respiration_rate",
    "motion_index": "b_motion_index",
    "quality": "b_quality",
}

RAW_VIEW = {
    "A": (
        ("alpha", "a_alpha_power", "", 1),
        ("beta", "a_beta_power", "", 1),
        ("theta/beta", "a_theta_beta_ratio", "", 2),
        ("EMG", "a_emg_amplitude_uv", " µV", 1),
    ),
    "B": (
        ("HR", "b_heart_rate", " bpm", 0),
        ("HRV", "b_hrv_rmssd", " ms", 0),
        ("GSR", "b_gsr_tonic_us", " µS", 1),
        ("temp", "b_skin_temp_c", " °C", 1),
        ("resp", "b_respiration_rate", " /min", 0),
        ("PSI", "b_pain_stress_index", "", 0),
    ),
    "C": (
        ("AU4", "c_au4", "", 1),
        ("AU7", "c_au7", "", 1),
        ("AU43", "c_au43", "", 1),
        ("rPPG", "c_rppg_hr", " bpm", 0),
        ("light", "c_lighting", "", 2),
    ),
}

FACE_MODEL = Path(environ.get("PAINSCORE_FACE_MODEL", ROOT / "backend" / "face_landmarker.task"))

BLENDSHAPE_UNITS = {
    "c_au4": ("browDownLeft", "browDownRight"),
    "c_au6": ("cheekSquintLeft", "cheekSquintRight"),
    "c_au7": ("eyeSquintLeft", "eyeSquintRight"),
    "c_au9": ("noseSneerLeft", "noseSneerRight"),
    "c_au10": ("mouthUpperUpLeft", "mouthUpperUpRight"),
    "c_au43": ("eyeBlinkLeft", "eyeBlinkRight"),
}

SMILE_SHAPES = ("mouthSmileLeft", "mouthSmileRight")
JAW_SHAPE = "jawOpen"
SMILE_THRESHOLD = 0.25
JAW_MOVEMENT = 0.045
UNIT_GAIN = 2.0
AU_CEILING = 5.0

FOREHEAD_LANDMARK = 10
TEMPLE_LANDMARKS = (234, 454)

TRACE_LENGTH = 420
RPPG_MINIMUM = 90


def bounded(value, low=0.0, high=1.0):
    return float(np.clip(value, low, high))


def blendshape_units(scores):
    units = {}
    for name, shapes in BLENDSHAPE_UNITS.items():
        present = [scores[shape] for shape in shapes if shape in scores]
        if not present:
            return None
        units[name] = AU_CEILING * bounded(UNIT_GAIN * float(np.mean(present)))
    return units


def pulse_from_trace(moments, greens):
    if len(moments) < RPPG_MINIMUM:
        return None
    seconds = np.asarray(moments, dtype=float)
    seconds = seconds - seconds[0]
    duration = float(seconds[-1])
    if duration < 6.0:
        return None
    grid = np.linspace(0.0, duration, int(duration * 30.0))
    trace = np.interp(grid, seconds, np.asarray(greens, dtype=float))
    trace = trace - np.polyval(np.polyfit(grid, trace, 2), grid)
    spread = float(np.std(trace))
    if spread <= 1e-6:
        return None
    spectrum = np.abs(np.fft.rfft((trace / spread) * np.hanning(len(trace))))
    frequencies = np.fft.rfftfreq(len(trace), float(grid[1] - grid[0]))
    band = (frequencies >= 0.7) & (frequencies <= 3.0)
    if not band.any():
        return None
    inside = spectrum[band]
    strength = float(inside.max() / (float(np.mean(inside)) + 1e-9))
    if strength < 3.0:
        return None
    return 60.0 * float(frequencies[band][int(np.argmax(inside))])


class Camera:
    def __init__(self, index=CAMERA_INDEX):
        self.index = index
        self.state = "off"
        self.detail = ""
        self.frames = 0
        self.pulse = None
        self.values = None
        self.lock = threading.Lock()
        self.halt = threading.Event()
        self.worker = None
        self.jaw = deque(maxlen=15)
        self.moments = deque(maxlen=TRACE_LENGTH)
        self.greens = deque(maxlen=TRACE_LENGTH)

    def start(self):
        if self.index < 0:
            self.state = "disabled"
            self.detail = "stream C simulated, set PAINSCORE_CAMERA=0 to read the webcam"
            return
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def stop(self):
        self.halt.set()
        if self.worker:
            self.worker.join(timeout=3.0)

    def snapshot(self):
        with self.lock:
            return dict(self.values) if self.values else None

    def status(self):
        return {
            "state": self.state,
            "detail": self.detail,
            "frames": self.frames,
            "rppg_bpm": round(self.pulse, 1) if self.pulse else None,
        }

    def _run(self):
        try:
            import cv2
        except Exception as problem:
            self.state = "unavailable"
            self.detail = f"opencv missing ({type(problem).__name__}), stream C simulated"
            return
        capture = cv2.VideoCapture(self.index)
        if not capture.isOpened():
            capture.release()
            self.state = "unavailable"
            self.detail = "no camera device, stream C simulated"
            return
        landmarker, wrap = self._open_landmarker()
        try:
            while not self.halt.is_set():
                received, frame = capture.read()
                if not received:
                    self.state = "unavailable"
                    self.detail = "camera stopped delivering frames, stream C simulated"
                    break
                try:
                    self._consume(cv2, landmarker, wrap, frame)
                except Exception as problem:
                    self.state = "unavailable"
                    self.detail = f"frame analysis failed ({type(problem).__name__}), stream C simulated"
                    self._publish(None)
                    break
                self.frames += 1
        finally:
            capture.release()
            if landmarker is not None:
                landmarker.close()

    def _open_landmarker(self):
        if not FACE_MODEL.exists():
            self.state = "lighting only"
            self.detail = f"{FACE_MODEL.name} not found, action units simulated"
            return None, None
        try:
            import mediapipe
            from mediapipe.tasks import python as tasks
            from mediapipe.tasks.python import vision

            landmarker = vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=tasks.BaseOptions(model_asset_path=str(FACE_MODEL)),
                    output_face_blendshapes=True,
                    num_faces=1,
                )
            )

            def wrap(pixels):
                return mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=pixels)

            self.state = "starting"
            self.detail = "waiting for a face"
            return landmarker, wrap
        except Exception as problem:
            self.state = "lighting only"
            self.detail = f"face landmarker unavailable ({type(problem).__name__}), action units simulated"
            return None, None

    def _consume(self, cv2, landmarker, wrap, frame):
        height, width = frame.shape[:2]
        if width > 480:
            frame = cv2.resize(frame, (480, round(height * 480 / width)))
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lighting = bounded(float(grey.mean()) / 150.0, 0.02, 1.0)
        reading = {"c_lighting": lighting}

        if landmarker is None:
            reading["c_quality"] = bounded(lighting * 0.9, 0.02, 0.99)
            self._publish(reading)
            return

        detected = landmarker.detect(wrap(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if not detected.face_blendshapes:
            reading["c_occluded"] = 1.0
            reading["c_quality"] = bounded(lighting * 0.15, 0.02, 0.99)
            self.state = "no face"
            self.detail = "no face in frame, stream C attenuated"
            self._publish(reading)
            return

        scores = {shape.category_name: float(shape.score) for shape in detected.face_blendshapes[0]}
        units = blendshape_units(scores)
        if units is None:
            reading["c_quality"] = bounded(lighting * 0.9, 0.02, 0.99)
            self.state = "lighting only"
            self.detail = "blendshape names not recognised, action units simulated"
            self._publish(reading)
            return

        self.jaw.append(scores.get(JAW_SHAPE, 0.0))
        smile = [scores[shape] for shape in SMILE_SHAPES if shape in scores]
        smiling = bool(smile) and float(np.mean(smile)) > SMILE_THRESHOLD
        talking = len(self.jaw) >= 8 and float(np.std(self.jaw)) > JAW_MOVEMENT

        reading.update(units)
        reading["c_occluded"] = 0.0
        reading["c_smile_detected"] = 1.0 if smiling else 0.0
        reading["c_talk_detected"] = 1.0 if talking else 0.0
        reading["c_quality"] = bounded(lighting * 0.97, 0.02, 0.99)
        self._sample_pulse(detected.face_landmarks[0], frame)
        if self.pulse:
            reading["c_rppg_hr"] = self.pulse
        self.state = "live"
        self.detail = "action units from face blendshapes"
        self._publish(reading)

    def _sample_pulse(self, landmarks, frame):
        height, width = frame.shape[:2]
        forehead = landmarks[FOREHEAD_LANDMARK]
        left, right = (landmarks[index] for index in TEMPLE_LANDMARKS)
        half = max(int(0.16 * abs(right.x - left.x) * width), 4)
        top = max(int(forehead.y * height) - half, 0)
        start = max(int(forehead.x * width) - half, 0)
        patch = frame[top : top + 2 * half, start : start + 2 * half, 1]
        if not patch.size:
            return
        self.moments.append(time.monotonic())
        self.greens.append(float(patch.mean()))
        if len(self.moments) >= RPPG_MINIMUM and self.frames % 15 == 0:
            self.pulse = pulse_from_trace(self.moments, self.greens)

    def _publish(self, reading):
        with self.lock:
            self.values = reading


class PatchBridge:
    def __init__(self, host=MQTT_HOST, port=MQTT_PORT):
        self.host = host
        self.port = port
        self.state = "off"
        self.detail = ""
        self.messages = 0
        self.client = None
        self.lock = threading.Lock()
        self.telemetry = {}

    def start(self):
        try:
            from paho.mqtt import client as mqtt
        except Exception as problem:
            self.state = "unavailable"
            self.detail = f"paho-mqtt missing ({type(problem).__name__}), patch telemetry simulated"
            return
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="painscore-server")
        client.on_connect = self._connected
        client.on_disconnect = self._disconnected
        client.on_message = self._received
        self.client = client
        self.state = "connecting"
        self.detail = f"{self.host}:{self.port}"
        try:
            client.connect_async(self.host, self.port, keepalive=30)
            client.loop_start()
        except Exception as problem:
            self.state = "unavailable"
            self.detail = f"{self.host}:{self.port} unreachable ({type(problem).__name__})"
            return
        threading.Timer(5.0, self._give_up).start()

    def stop(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    def status(self):
        return {"state": self.state, "detail": self.detail, "messages": self.messages}

    def snapshot(self):
        with self.lock:
            return dict(self.telemetry)

    def publish(self, subject, payload):
        if self.state != "connected" or self.client is None:
            return
        try:
            self.client.publish(f"{ESTIMATE_TOPIC}/{subject}", json.dumps(payload), qos=0)
        except Exception:
            pass

    def _give_up(self):
        if self.state == "connecting":
            self.state = "no broker"
            self.detail = f"no broker on {self.host}:{self.port}, patch telemetry simulated"

    def _connected(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            self.state = "refused"
            self.detail = f"broker refused the connection ({reason_code})"
            return
        self.state = "connected"
        self.detail = f"{self.host}:{self.port} subscribed to {TELEMETRY_TOPIC}"
        client.subscribe(TELEMETRY_TOPIC, qos=0)

    def _disconnected(self, *arguments):
        if self.state == "connected":
            self.state = "connecting"
            self.detail = f"lost {self.host}:{self.port}, retrying"

    def _received(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode())
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        accepted = {}
        for key in TELEMETRY_FIELDS:
            if isinstance(payload.get(key), (int, float)):
                accepted[key] = float(payload[key])
        if not accepted:
            return
        with self.lock:
            self.telemetry = accepted
        self.messages += 1


def apply_telemetry(window, patient, telemetry):
    for key, column in TELEMETRY_FIELDS.items():
        if key in telemetry:
            window[column] = telemetry[key]
    window["b_hr_delta"] = window["b_heart_rate"] - patient.heart_rate
    window["b_gsr_delta_us"] = window["b_gsr_tonic_us"] - patient.gsr
    window["b_temp_delta_c"] = window["b_skin_temp_c"] - patient.skin_temp
    window["b_resp_delta"] = window["b_respiration_rate"] - patient.respiration
    window["b_hrv_sdnn"] = window["b_hrv_rmssd"] * 1.4
    window["b_pain_stress_index"] = simulate.stress_index(
        patient,
        window["b_heart_rate"],
        window["b_hrv_rmssd"],
        window["b_gsr_tonic_us"],
        window["b_respiration_rate"],
    )
    if "quality" not in telemetry:
        window["b_quality"] = float(np.clip(0.95 * (1.0 - 0.30 * window["b_motion_index"]), 0.02, 0.99))


class LiveSession:
    def __init__(self, platform, patient):
        self.platform = platform
        self.patient = patient
        self.rng = np.random.default_rng()
        self.index = 0
        self.scenario = "rest"
        self.level = 6
        self.context = patient.context
        self.role = SERVICE_ROLE
        self.notice = ""

    def control(self, message):
        if not isinstance(message, dict):
            return
        role = message.get("role")
        if role in PERMISSIONS:
            self.role = role
            self.notice = ""
        context = message.get("context")
        if context in self.platform.fusion.contexts:
            self.context = context
        level = message.get("level")
        if isinstance(level, (int, float)):
            self.level = int(np.clip(int(level), 1, 10))
        scenario = message.get("scenario")
        if scenario in SCENARIOS:
            if permitted(self.role, "change_scenario"):
                self.scenario = scenario
                self.platform.note(self.role, "scenario.change", self.patient.identifier)
                self.notice = ""
            else:
                self.notice = f"role {self.role} may not change the scenario"

    def build(self):
        scenario = self.scenario
        failed = ""
        if scenario == "sensor_failure":
            failed = FAILURE_CYCLE[(self.index // FAILURE_WINDOWS) % len(FAILURE_CYCLE)]
            scenario = "pain"
        pain = self.level if scenario in ("pain", "sedated") else 0
        context = "unconscious_sedated" if self.scenario == "sedated" else self.context

        window = {
            "patient_id": self.patient.identifier,
            "window_index": self.index,
            "scenario": scenario,
            "failed_stream": failed,
            "clinical_context": context,
            simulate.LABEL_COLUMN: pain,
            simulate.SELF_REPORT_COLUMN: simulate.self_report(self.patient, pain, scenario, self.rng),
            simulate.CONFOUNDER_COLUMN: simulate.confounder_class(scenario, pain),
        }
        window.update(simulate.neuromuscular(self.patient, pain, scenario, self.rng))
        patch = simulate.smart_patch(self.patient, pain, scenario, self.rng)
        window.update(patch)
        window.update(
            simulate.contextual(
                self.patient, pain, scenario, self.rng, patch["b_motion_index"], patch["b_heart_rate"]
            )
        )
        window.update(simulate.therapy_flags(pain, self.rng))

        telemetry = self.platform.bridge.snapshot()
        if telemetry:
            apply_telemetry(window, self.patient, telemetry)
        observed = self.platform.camera.snapshot()
        if observed:
            window.update(observed)

        if failed == "all":
            for stream in simulate.STREAMS:
                simulate.fail_stream(window, stream, self.rng)
        elif failed:
            simulate.fail_stream(window, failed, self.rng)
        return window, failed

    def step(self):
        window, failed = self.build()
        estimate = self.platform.fusion.estimate(window, window["clinical_context"])
        envelope, entry = self.platform.seal(self.patient.identifier, estimate)
        self.platform.bridge.publish(
            self.patient.identifier,
            {
                "estimated_pain": estimate["estimated_pain"],
                "confidence": estimate["confidence"],
                "status": estimate["status"],
            },
        )

        readable = permitted(self.role, "read_estimates") or permitted(self.role, "read_own_estimate")
        frame = {
            "type": "window",
            "sequence": self.index,
            "subject": self.patient.identifier,
            "scenario": self.scenario,
            "effective_scenario": window["scenario"],
            "clinical_context": window["clinical_context"],
            "failed_stream": failed,
            "role": self.role,
            "notice": self.notice,
            "ground_truth": window[simulate.LABEL_COLUMN],
            "self_report": window[simulate.SELF_REPORT_COLUMN],
            "therapy": {name: int(window[name]) for name in simulate.THERAPY_COLUMNS},
            "camera": self.platform.camera.status(),
            "patch_link": self.platform.bridge.status(),
            "sealed_bytes": len(envelope["ciphertext"]) // 2,
            "audit_index": entry.index,
            "audit_hash": entry.entry_hash[:16],
            "withheld": [],
        }

        if readable:
            frame["estimate"] = {
                key: estimate[key]
                for key in (
                    "status",
                    "estimated_pain",
                    "confidence",
                    "stream_scores",
                    "confounder_class",
                    "classifier_class",
                    "confounder_alert",
                    "observations",
                    "contributing_signals",
                )
            }
        else:
            frame["withheld"].append("pain estimate")

        if permitted(self.role, "read_quality"):
            frame["quality"] = {
                key: estimate[key]
                for key in ("signal_quality", "attenuation", "attenuation_reasons", "weights", "remaining_weight")
            }
        else:
            frame["withheld"].append("signal quality and weights")

        if permitted(self.role, "read_raw_signals"):
            frame["raw"] = {
                stream: [
                    {"label": label, "value": f"{window[column]:.{decimals}f}{unit}"}
                    for label, column, unit, decimals in RAW_VIEW[stream]
                ]
                for stream in simulate.STREAMS
            }
        else:
            frame["withheld"].append("raw signals")

        self.index += 1
        return frame


class Platform:
    def __init__(self):
        self.fusion = None
        self.security = None
        self.results = None
        self.camera = Camera()
        self.bridge = PatchBridge()
        self.connections = 0
        self.lock = threading.Lock()

    def start(self):
        self.fusion = load()
        self.security = SecureSession()
        for patient in PATIENTS:
            self.security.consent.grant(patient.identifier)
        self.security.audit.append("patient", "consent.grant", f"{len(PATIENTS)} pseudonymised subjects")
        self.results = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else None
        self.camera.start()
        self.bridge.start()

    def stop(self):
        self.camera.stop()
        self.bridge.stop()

    def session(self):
        with self.lock:
            patient = PATIENTS[self.connections % len(PATIENTS)]
            self.connections += 1
            self.security.start(patient.identifier, SERVICE_ROLE)
        return LiveSession(self, patient)

    def seal(self, subject, estimate):
        with self.lock:
            envelope = self.security.record_estimate(SERVICE_ROLE, subject, estimate)
            return envelope, self.security.audit.chain[-1]

    def note(self, role, action, subject):
        with self.lock:
            self.security.audit.append(role, action, subject)

    def greeting(self, session):
        learned = json.loads(LEARNED_PATH.read_text()) if LEARNED_PATH.exists() else {}
        return {
            "type": "hello",
            "subject": session.patient.identifier,
            "scenarios": list(SCENARIOS),
            "contexts": list(self.fusion.contexts),
            "context": session.context,
            "interval": INTERVAL,
            "insufficient": INSUFFICIENT,
            "layer_mix": self.fusion.mix,
            "learned_weights": {"statistical": self.fusion.statistical, "ml": self.fusion.ml},
            "learned_detail": learned.get("detail", {}),
            "stream_names": simulate.STREAM_NAMES,
            "roles": {role: sorted(rights) for role, rights in PERMISSIONS.items()},
            "security": self.security.status(),
            "results": self.results,
        }


def bootstrap():
    if not simulate.DATASET_PATH.exists():
        print("dataset missing, generating synthetic windows", flush=True)
        simulate.main()
    if not (LEARNED_PATH.exists() and ARTIFACT_PATH.exists()):
        print("learned weights missing, training layers 2 and 3", flush=True)
        train.main()


PLATFORM = Platform()


@asynccontextmanager
async def lifespan(application):
    bootstrap()
    PLATFORM.start()
    print(f"dashboard on http://{HOST}:{PORT}", flush=True)
    yield
    PLATFORM.stop()


app = FastAPI(title="Pain Score multimodal estimation", lifespan=lifespan)


@app.get("/api/scenarios")
def scenarios():
    return {
        "scenarios": list(SCENARIOS),
        "contexts": PLATFORM.fusion.contexts,
        "layer_mix": PLATFORM.fusion.mix,
        "failure_cycle": list(FAILURE_CYCLE),
    }


@app.get("/api/results")
def results():
    if PLATFORM.results is None:
        return JSONResponse({"detail": "no evaluation yet, run python ai/train.py"}, status_code=404)
    return PLATFORM.results


@app.get("/api/security")
def security():
    return PLATFORM.security.status()


@app.get("/api/audit")
def audit(role: str = "doctor", limit: int = 20):
    if not permitted(role, "read_audit"):
        return JSONResponse({"detail": f"role {role} may not read the audit log"}, status_code=403)
    return {"entries": PLATFORM.security.audit.records(limit)}


@app.post("/api/verify")
def verify(role: str = "admin"):
    if not permitted(role, "verify_audit"):
        return JSONResponse({"detail": f"role {role} may not verify the audit chain"}, status_code=403)
    verified, message = PLATFORM.security.audit.verify()
    return {"verified": verified, "message": message, "entries": len(PLATFORM.security.audit.chain)}


@app.websocket("/ws")
async def feed(socket: WebSocket):
    await socket.accept()
    session = PLATFORM.session()
    await socket.send_json(PLATFORM.greeting(session))
    closed = asyncio.Event()

    async def listen():
        try:
            while True:
                session.control(await socket.receive_json())
        except Exception:
            closed.set()

    listener = asyncio.create_task(listen())
    try:
        while not closed.is_set():
            await socket.send_json(await asyncio.to_thread(session.step))
            try:
                await asyncio.wait_for(closed.wait(), timeout=INTERVAL)
            except asyncio.TimeoutError:
                pass
    except Exception:
        pass
    finally:
        listener.cancel()


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="dashboard")


def free_port(host, first):
    for candidate in range(first, first + 10):
        with socket.socket() as probe:
            if probe.connect_ex((host, candidate)) != 0:
                return candidate
    return first


def main():
    global PORT

    chosen = free_port(HOST, PORT)
    if chosen != PORT:
        print(f"port {PORT} is already in use, serving on {chosen} instead", flush=True)
        PORT = chosen
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
