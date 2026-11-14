"""Service-owned camera verifier. Private stdio only; no credential material.

Installed with an isolated Python runtime in an administrator-owned directory.
Each process handles one profile validation or one fresh camera challenge.
--prewarm prepares models without a profile; idle standby keeps the camera closed.
Selected scans can open the camera alongside the remaining model preparation.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
from time import sleep

# -I ignores PYTHONPATH and user site packages. Only this installed code root is added.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from backend.viso.native import Camera, NativeHost
from backend.viso.recognition import FaceEngine, MODEL_ID
from backend.viso.service import SandboxService
from backend.viso.storage import ProfileStore
from backend.viso.enrollment import validate_circular_profile, STEPS


def validate_profile(profile):
    if not isinstance(profile, dict) or profile.get("model_id") != MODEL_ID:
        raise ValueError("Enroll with the current Viso recognition model first.")
    if profile.get("source") != "camera" or profile.get("guided") is not True:
        raise ValueError("Windows sign-in requires a completed guided camera enrollment.")
    if profile.get("enrollment_version") or "template_groups" in profile:
        validate_circular_profile(profile)
        samples = len(STEPS)
    else:
        samples = 5
        if type(profile.get("samples")) is not int or profile["samples"] != samples:
            raise ValueError("Windows sign-in requires a completed guided camera enrollment.")
    for key, shape in (("embedding", (128,)), ("templates", (samples, 128))):
        values = np.asarray(profile.get(key), dtype=np.float32)
        if values.shape != shape or not np.isfinite(values).all():
            raise ValueError("Invalid face profile.")
        norms = np.linalg.norm(values, axis=-1)
        if not np.allclose(norms, 1, atol=.01):
            raise ValueError("Invalid face profile normalization.")
    if not isinstance(profile.get("id"), str) or not 1 <= len(profile["id"]) <= 64:
        raise ValueError("Invalid face profile identifier.")
    return profile


def verify(host, emit, acknowledge, start=None):
    if start is None:
        start = host.handle("camera.start", {"index": host.signin_camera,
                                             "exposure_assist": host.signin_exposure_assist})
    lighting = start.get("lighting")
    exposure = start.get("exposure", "off")
    host.handle("attempt.start", {"threshold": .55})
    last_message = None
    while True:
        result = host.handle("attempt.tick", {})
        attempt = result["attempt"]
        if attempt["state"] == "unlocked":
            # Restore camera controls before the service may retire this worker.
            host.handle("camera.stop", {})
            emit({"event": "accepted"})
            return
        if attempt["state"] != "scanning":
            raise ValueError(attempt["message"])
        message = attempt["message"]
        exposure = host.camera.diagnostics().get("exposure", exposure)
        observed = result.get("observation", {}).get("lighting")
        if observed:
            lighting = observed
        # Keep the actual challenge first: lighting guidance must never replace
        # or invent a blink prompt. Only bounded advisory text crosses the pipe.
        if lighting:
            message += (" Face lighting: " if lighting.get("scope") == "face" else " Scene lighting: ") + lighting["message"]
        if exposure == "tuned":
            message += " Exposure assistance active."
        elif exposure in ("unsupported", "limited", "restore_failed"):
            message += " Exposure assistance unavailable; use better lighting."
        if result.get("prompt_pending"):
            emit({"event": "prompt", "message": message})
            if not acknowledge():
                raise ValueError("Sign-in canceled.")
            host.handle("attempt.ack", {})
            last_message = message
        elif message != last_message:
            emit({"event": "status", "message": message})
            last_message = message
        sleep(.025)


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    output_lock = threading.Lock()
    def emit(message):
        with output_lock:
            print(json.dumps(message, allow_nan=False), flush=True)
    camera = engine = host = None
    preparation = models = None
    def prepare_models():
        prepared = None
        try:
            prepared = FaceEngine(ROOT / "models")
            prepared.warmup()
            emit({"event": "ready"})
            return prepared
        except Exception as error:
            if prepared is not None:
                prepared.close()
            emit({"event": "error", "message": str(error)})
            raise
    try:
        if "--prewarm" in sys.argv[1:]:
            # Drain the service request while blank-input preparation runs. No
            # profile enters this task, and idle standby never creates a camera.
            preparation = ThreadPoolExecutor(max_workers=1, thread_name_prefix="viso-models")
            models = preparation.submit(prepare_models)
        line = sys.stdin.readline(131073)
        if len(line) > 131072:
            raise ValueError("Face profile is too large.")
        request = json.loads(line)
        profile = validate_profile(request["profile"])
        if request.get("command") == "validate":
            if models is not None:
                engine = models.result()
            emit({"event": "validated"})
            return
        if request.get("command") != "verify":
            raise ValueError("Unsupported sign-in command.")
        # Only the authenticated, selected verify request opens a camera. Its
        # driver/exposure preparation can overlap the remaining model load.
        # Keep ready as the first successful prewarm event for the service's
        # sole initialization reader; never let camera status precede it.
        if models is None or models.done():
            if models is not None:
                engine = models.result()
            emit({"event": "status", "message": "Starting camera. Look straight ahead with both eyes open."})
        camera = Camera(lambda event: None, preview=False)
        start = camera.start(request.get("camera", 0), request.get("exposure_assist", False))
        if models is not None:
            engine = models.result()
        if engine is None:
            engine = FaceEngine(ROOT / "models")
        store = ProfileStore(ROOT, ephemeral=True)
        store.profile = profile
        host = NativeHost(SandboxService(engine, store), camera)
        host.signin_camera = request.get("camera", 0)
        host.signin_exposure_assist = request.get("exposure_assist", False)
        # attempt.start discards startup frames and timestamps the fresh scan.
        # No startup image or blink can become authentication evidence.
        verify(host, emit, lambda: sys.stdin.readline(128).strip() == "ack", start=start)
    except Exception as error:
        if camera is not None:
            try:
                camera.stop()
            except Exception:
                pass
        emit({"event": "error", "message": str(error)})
        sys.exit(1)
    finally:
        try:
            if host is not None:
                host.cancel()
            if camera is not None:
                camera.stop()
        finally:
            # Close a successfully prepared engine even if the request or camera
            # failed before its result was adopted. The service Job still bounds
            # a blocked native startup and kills all work on cancellation.
            if preparation is not None:
                preparation.shutdown(wait=True)
                if engine is None:
                    try:
                        engine = models.result()
                    except Exception:
                        pass
            if engine is not None:
                engine.close()


if __name__ == "__main__":
    main()
