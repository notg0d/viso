"""Service-owned camera verifier. Private stdio only; no credential material.

Installed with an isolated Python runtime in an administrator-owned directory.
Each process handles one profile validation or one fresh camera challenge.
--prewarm loads models before receiving any profile; the camera stays closed.
"""
import json
from pathlib import Path
import sys
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


def verify(host, emit, acknowledge):
    host.handle("camera.start", {"index": host.signin_camera})
    host.handle("attempt.start", {"threshold": .55})
    last_message = None
    while True:
        result = host.handle("attempt.tick", {})
        attempt = result["attempt"]
        if attempt["state"] == "unlocked":
            emit({"event": "accepted"})
            return
        if attempt["state"] != "scanning":
            raise ValueError(attempt["message"])
        message = attempt["message"]
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
    def emit(message):
        print(json.dumps(message, allow_nan=False), flush=True)
    camera = engine = host = None
    try:
        if "--prewarm" in sys.argv[1:]:
            engine = FaceEngine(ROOT / "models")
            emit({"event": "ready"})
        line = sys.stdin.readline(131073)
        if len(line) > 131072:
            raise ValueError("Face profile is too large.")
        request = json.loads(line)
        profile = validate_profile(request["profile"])
        if request.get("command") == "validate":
            emit({"event": "validated"})
            return
        if request.get("command") != "verify":
            raise ValueError("Unsupported sign-in command.")
        emit({"event": "status", "message": "Starting camera. Look straight ahead with both eyes open."})
        if engine is None:
            engine = FaceEngine(ROOT / "models")
        store = ProfileStore(ROOT, ephemeral=True)
        store.profile = profile
        camera = Camera(lambda event: None, preview=False)
        host = NativeHost(SandboxService(engine, store), camera)
        host.signin_camera = request.get("camera", 0)
        verify(host, emit, lambda: sys.stdin.readline(128).strip() == "ack")
    except Exception as error:
        emit({"event": "error", "message": str(error)})
        sys.exit(1)
    finally:
        if host is not None:
            host.cancel()
        if camera is not None:
            camera.stop()
        if engine is not None:
            engine.close()


if __name__ == "__main__":
    main()
