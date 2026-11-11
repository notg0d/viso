"""Private, line-delimited JSON child process for the native Windows application.

The desktop owns these pipes. No socket, HTTP host, or browser is involved.
Camera capture has its own clock/thread so inference cannot swallow a short blink.
"""

import argparse
import base64
from collections import deque
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import struct
import sys
import threading
from time import monotonic

import cv2
import numpy as np

from .recognition import FaceEngine, MODEL_ID
from .service import ApiError, SandboxService
from .storage import ProfileStore

ROOT = Path(__file__).resolve().parents[2]


class Camera:
    START_TIMEOUT = 12
    STOP_TIMEOUT = 3
    FIRST_FRAME_READS = 3

    def __init__(self, emit, preview=True):
        self.emit = emit
        self.preview = preview
        self.lock = threading.Lock()
        self.frames = deque(maxlen=6)
        self.latest = None
        self.error = None
        self.stopped = threading.Event()
        self.thread = None
        self.generation = 0
        self.details = {}
        self.sample_times = deque(maxlen=40)
        self.unreleased_device = None

    @staticmethod
    def valid_frame(image):
        return (isinstance(image, np.ndarray) and image.dtype == np.uint8
                and image.ndim == 3 and image.shape[2] == 3 and image.size > 0)

    def diagnostics(self):
        # An allowlisted snapshot only: never images, device names/paths, raw
        # driver exceptions, profile metadata, identity/eye scores or credentials.
        now = monotonic()
        with self.lock:
            result = dict(self.details)
            result["attempts"] = [dict(attempt) for attempt in self.details.get("attempts", [])]
            latest = self.latest
            times = list(self.sample_times)
            result["buffered_frames"] = len(self.frames)
        active = self.thread is not None and self.thread.is_alive()
        result.update(running=active and latest is not None and not self.stopped.is_set() and not self.error,
                      driver_active=active, stop_requested=self.stopped.is_set(),
                      frame_age_ms=round(max(0, now - latest[0]) * 1000, 1) if latest else None,
                      capture_hz=round((len(times) - 1) / (times[-1] - times[0]), 1)
                      if len(times) > 1 and times[-1] > times[0] else None)
        return result

    def start(self, index):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 32:
            raise ApiError("Choose an available camera.")
        self.stop()
        self.error = None
        self.stopped.clear()
        started = monotonic()
        deadline = started + self.START_TIMEOUT
        with self.lock:
            self.sample_times.clear()
            self.details = {"index": index, "backend": None, "width": None, "height": None,
                            "startup_ms": None, "failure": None, "attempts": []}
        opened = threading.Event()
        startup_complete = False
        self.generation += 1
        generation = self.generation

        def capture():
            nonlocal startup_complete
            device = None

            def interrupted():
                if self.stopped.is_set():
                    raise ApiError("Camera startup canceled.")
                if monotonic() >= deadline:
                    raise ApiError("The camera took too long to open. Check Windows camera permissions.")

            def release_device():
                nonlocal device
                if device is not None:
                    # A failed/blocked release must not lead to a second owner.
                    current = device
                    device = None
                    try:
                        current.release()
                    except Exception:
                        self.unreleased_device = current
                        with self.lock:
                            self.details["failure"] = "release_failed"
                        raise ApiError("Camera driver did not release the device. Close Viso and restart the camera.")

            try:
                # OpenCV 4.13's DirectShow constructor negotiates size before
                # starting the graph. Setting size/FPS after open restarts the
                # driver twice; use its negotiated cadence and timestamp every
                # frame instead of forcing a nominal 30 fps.
                # Some drivers reject open-time parameters or open a handle but
                # never supply frames. Try defaults, then Media Foundation, once
                # each and serially, within the SAME startup deadline. CAP_ANY
                # would repeat an unspecified backend and is deliberately absent.
                candidates = [("DirectShow", cv2.CAP_DSHOW, "negotiated", [
                    cv2.CAP_PROP_FRAME_WIDTH, 960, cv2.CAP_PROP_FRAME_HEIGHT, 720]),
                    ("DirectShow", cv2.CAP_DSHOW, "default", None),
                    ("Media Foundation", cv2.CAP_MSMF, "default", None)]
                image = None
                for backend, api, configuration, parameters in candidates:
                    interrupted()
                    attempt_started = monotonic()
                    attempt = {"backend": backend, "configuration": configuration, "outcome": "opening"}
                    with self.lock:
                        self.details["attempts"].append(attempt)
                    outcome = "driver_error"
                    try:
                        device = cv2.VideoCapture(index, api, parameters) if parameters else cv2.VideoCapture(index, api)
                        interrupted()
                        outcome = "not_opened"
                        if device.isOpened():
                            outcome = "no_frame"
                            for _ in range(self.FIRST_FRAME_READS):
                                interrupted()
                                ok, candidate = device.read()
                                interrupted()
                                if ok and self.valid_frame(candidate):
                                    image = candidate
                                    outcome = "opened"
                                    break
                    except ApiError:
                        outcome = "stopped" if self.stopped.is_set() else "timeout"
                        raise
                    except Exception:
                        outcome = "driver_error"
                    finally:
                        with self.lock:
                            attempt.update(outcome=outcome, elapsed_ms=round((monotonic() - attempt_started) * 1000, 1))
                        if outcome != "opened":
                            release_device()
                    if image is not None:
                        with self.lock:
                            self.details["backend"] = backend
                        break
                if image is None:
                    raise ApiError("Camera unavailable. Close other camera apps, check Windows desktop-app camera permissions, and choose the device in Settings.")
                last_preview = last_sample = 0
                while not self.stopped.is_set():
                    if image is None:
                        ok, image = device.read()
                        if not ok or not self.valid_frame(image):
                            raise ApiError("The camera disconnected or stopped providing frames. Reconnect it and start a new test.")
                    if self.stopped.is_set():
                        break
                    now = monotonic()
                    if not startup_complete:
                        interrupted()
                    # Keep each 30 fps frame: a 35 ms gate would halve a webcam's
                    # evidence rate to 15 fps and could miss brief blinks.
                    if now - last_sample < .025:
                        image = None
                        continue
                    last_sample = now
                    height, width = image.shape[:2]
                    if max(height, width) > 960:
                        image = cv2.resize(image, (round(width * 960 / max(height, width)), round(height * 960 / max(height, width))))
                    # Recognition owns raw, immutable samples. JPEG is only a UI
                    # transport, never an intermediate inference representation.
                    image.setflags(write=False)
                    with self.lock:
                        if self.stopped.is_set():
                            break
                        self.latest = (now, image)
                        self.frames.append(self.latest)
                        self.sample_times.append(now)
                        self.details.update(width=width, height=height)
                        if not startup_complete:
                            self.details["startup_ms"] = round((now - started) * 1000, 1)
                    startup_complete = True
                    opened.set()
                    if self.preview and now - last_preview >= 1 / 15:
                        last_preview = now
                        view = image
                        if max(image.shape[:2]) > 720:
                            scale = 720 / max(image.shape[:2])
                            view = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)))
                        ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if ok and not self.stopped.is_set():
                            self.emit({"event": "preview", "image": base64.b64encode(jpeg).decode("ascii"), "generation": generation})
                    image = None
            except Exception as error:
                if not self.stopped.is_set():
                    self.error = error.message if isinstance(error, ApiError) else "Camera driver failed. Close Viso and restart the camera."
                    with self.lock:
                        if self.details["failure"] != "release_failed":
                            self.details["failure"] = "capture_failed" if startup_complete else "startup_failed"
                        self.latest = None
                        self.frames.clear()
                    self.emit({"event": "camera_error", "message": self.error, "generation": generation})
            finally:
                try:
                    release_device()
                except Exception:
                    # Retire this Camera, even if a failed release killed its
                    # thread. Reusing it cannot safely establish sole ownership.
                    self.error = "Camera driver did not release the device. Close Viso and restart the camera."
                    with self.lock:
                        self.details["failure"] = "release_failed"
                        self.latest = None
                        self.frames.clear()
                finally:
                    opened.set()

        self.thread = threading.Thread(target=capture, name="viso-camera", daemon=True)
        self.thread.start()
        if not opened.wait(max(0, deadline - monotonic())):
            with self.lock:
                self.details["failure"] = "startup_timeout"
            self.stop()
            raise ApiError("The camera took too long to open. Check Windows camera permissions.")
        if self.error:
            raise ApiError(self.error)
        if self.stopped.is_set() or not startup_complete:
            raise ApiError("Camera startup canceled.")
        return {"running": True, "generation": generation, "backend": self.details["backend"],
                "startup_ms": self.details["startup_ms"]}

    def stop(self):
        self.stopped.set()
        # Drop retained camera images immediately, even if a driver blocks join.
        with self.lock:
            self.latest = None
            self.frames.clear()
        if self.thread is not None:
            self.thread.join(timeout=self.STOP_TIMEOUT)
            if self.thread.is_alive():
                # Never reopen another device while a stuck driver still owns it.
                raise ApiError("Camera driver did not stop. Close Viso and restart the camera.")
        self.thread = None
        with self.lock:
            self.latest = None
            self.frames.clear()
            release_failed = self.details.get("failure") == "release_failed"
        if release_failed:
            raise ApiError("Camera driver did not release the device. Close Viso and restart the camera.")

    def discard(self):
        with self.lock:
            self.frames.clear()

    def frame(self):
        return self.sample()[1]

    def sample(self):
        with self.lock:
            latest = self.latest
        if self.error:
            raise ApiError(self.error)
        if latest is None or monotonic() - latest[0] > .7:
            raise ApiError("No fresh camera frame. Start your camera again.")
        return latest

    def take(self, after):
        if self.error:
            raise ApiError(self.error)
        now = monotonic()
        with self.lock:
            frames = [frame for frame in self.frames if frame[0] > after and now - frame[0] < .45]
            self.frames.clear()
        return frames


class NativeHost:
    def __init__(self, service, camera):
        self.service = service
        self.camera = camera
        self.enrollment_id = None
        self.attempt_id = None
        self.capture_after = 0
        self.awaiting_prompt = False

    def cancel(self):
        if self.enrollment_id and self.service.enrollment is not None:
            self.service.dispatch("DELETE", "/api/enrollments/" + self.enrollment_id)
        if self.attempt_id in self.service.attempts:
            self.service.dispatch("DELETE", "/api/attempts/" + self.attempt_id)
        self.enrollment_id = self.attempt_id = None
        self.awaiting_prompt = False
        self.camera.discard()

    def handle(self, command, data):
        dispatch = self.service.dispatch
        if command == "diagnostics":
            try:
                mediapipe_version = version("mediapipe")
            except PackageNotFoundError:
                mediapipe_version = None
            return {"schema": 1, "runtime": {"python": ".".join(map(str, sys.version_info[:3])),
                    "bits": struct.calcsize("P") * 8, "isolated": bool(sys.flags.isolated),
                    "numpy": np.__version__, "opencv": cv2.__version__, "mediapipe": mediapipe_version},
                    "engine": {"ready": self.service.engine is not None, "loading": self.service.engine_loading,
                               "model": MODEL_ID}, "storage": self.service.store.label,
                    "storage_error": bool(self.service.store.error), "camera": self.camera.diagnostics()}
        if command == "status":
            result = dispatch("GET", "/api/status")
            result.pop("token", None)
            return result
        if command == "camera.start":
            self.cancel()
            return self.camera.start(data.get("index", 0))
        if command == "camera.stop":
            self.cancel()
            self.camera.stop()
            return {"running": False}
        if command == "cancel":
            self.cancel()
            return {"state": "locked"}
        if command == "profile.delete":
            self.cancel()
            return dispatch("DELETE", "/api/profile")
        if command == "enrollment.start":
            self.camera.frame()
            self.cancel()
            result = dispatch("POST", "/api/enrollments", data)
            self.enrollment_id = result["id"]
            self.capture_after = 0
            return {"enrollment": result}
        if command == "enrollment.tick":
            if not self.enrollment_id:
                raise ApiError("Start enrollment first.")
            captured, image = self.camera.sample()
            if captured <= self.capture_after:
                return {"enrollment": self.service.enrollment.public()}
            self.capture_after = captured
            return dispatch("POST", "/api/enrollments/" + self.enrollment_id + "/frame", {"image": image})
        if command == "enrollment.finish":
            if not self.enrollment_id:
                raise ApiError("Start enrollment first.")
            result = dispatch("POST", "/api/enrollments/" + self.enrollment_id + "/finish")
            self.enrollment_id = None
            return result
        if command == "attempt.start":
            self.camera.frame()
            self.cancel()
            result = dispatch("POST", "/api/attempts", {"source": "camera", "threshold": data.get("threshold", .55)})
            self.attempt_id = result["id"]
            self.capture_after = self.service.attempts[self.attempt_id].started_at
            self.camera.discard()
            return {"attempt": result}
        if command == "attempt.ack":
            # Called only after the native UI has presented the new prompt.
            # Discard frames captured before that point, including in-flight ones.
            self.capture_after = monotonic()
            self.camera.discard()
            self.awaiting_prompt = False
            return {"acknowledged": True}
        if command == "attempt.tick":
            if not self.attempt_id or self.attempt_id not in self.service.attempts:
                raise ApiError("Start an unlock test first.")
            attempt = self.service.attempts[self.attempt_id]
            if monotonic() - attempt.started_at > 20:
                return {"attempt": attempt.observe(None)}
            if self.awaiting_prompt:
                return {"attempt": attempt.public(), "prompt_pending": True}
            samples = self.camera.take(self.capture_after)
            if not samples:
                self.camera.frame()  # Detect a stopped/disconnected camera.
                return {"attempt": attempt.public()}
            challenge = attempt.challenge
            result = dispatch("POST", "/api/attempts/" + self.attempt_id + "/frames", {"frames": [
                {"offset_ms": (captured - attempt.started_at) * 1000, "image": image}
                for captured, image in samples
            ]})
            self.capture_after = samples[-1][0]
            if attempt.challenge != challenge:
                self.awaiting_prompt = True
                result["prompt_pending"] = True
            return result
        if command == "analyze":
            return dispatch("POST", "/api/analyze", {"image": data.get("image") or self.camera.frame()})
        if command == "image.enroll":
            self.cancel()
            return dispatch("POST", "/api/enroll", {"name": data.get("name"), "source": "image", "images": data.get("images")})
        if command == "image.test":
            self.cancel()
            result = dispatch("POST", "/api/attempts", {"source": "image", "threshold": data.get("threshold", .55)})
            try:
                return dispatch("POST", "/api/attempts/" + result["id"] + "/frame", {"image": data.get("image")})
            finally:
                dispatch("DELETE", "/api/attempts/" + result["id"])
        raise ApiError("Unknown desktop command.", 404)


def main():
    parser = argparse.ArgumentParser(description="Viso native recognition worker")
    parser.add_argument("--ephemeral", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".viso")
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    output_lock = threading.Lock()

    def emit(message):
        with output_lock:
            print(json.dumps(message, ensure_ascii=True, allow_nan=False), flush=True)

    camera = Camera(emit)
    service = SandboxService(None, ProfileStore(args.data_dir, args.ephemeral), "Loading recognition models…")
    service.engine_loading = True
    host = NativeHost(service, camera)
    emit({"event": "ready"})

    def load_models():
        engine = None
        error = None
        try:
            engine = FaceEngine(ROOT / "models")
        except Exception as failure:
            error = str(failure)
        with service.lock:
            service.engine, service.engine_error = engine, error
            service.engine_loading = False
        emit({"event": "engine_ready"})

    loader = threading.Thread(target=load_models, name="viso-models")
    loader.start()
    try:
        while True:
            line = sys.stdin.readline(16_000_001)
            if not line:
                break
            if len(line) > 16_000_000:
                break
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or not isinstance(request.get("data", {}), dict):
                    raise ValueError("Expected a request object.")
                if request.get("command") == "shutdown":
                    break
                result = host.handle(request.get("command"), request.get("data", {}))
                emit({"id": request.get("id"), "result": result})
            except (ApiError, ValueError, TypeError, OSError) as error:
                emit({"id": request.get("id") if isinstance(request, dict) else None, "error": str(error) if not isinstance(error, ApiError) else error.message})
            except Exception as error:
                print("[Viso native] " + type(error).__name__ + ": " + str(error), file=sys.stderr)
                emit({"id": request.get("id"), "error": "The recognition engine could not complete this request."})
    finally:
        try:
            host.cancel()
            camera.stop()
        finally:
            loader.join()
            if service.engine is not None:
                service.engine.close()


if __name__ == "__main__":
    main()
