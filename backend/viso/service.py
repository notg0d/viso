import math
import secrets
import threading
from datetime import datetime, timezone
from time import monotonic

import numpy as np

from .recognition import DEFAULT_THRESHOLD, MODEL_ID, FaceEngine, InputError, Observation, decode_image, normalized, profile_similarity, similarity
from .sessions import Attempt
from .enrollment import Enrollment
from .storage import ProfileStore


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status


class SandboxService:
    def __init__(self, engine: FaceEngine | None, store: ProfileStore, engine_error: str | None = None):
        self.engine = engine
        self.store = store
        self.engine_error = engine_error
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.attempts: dict[str, Attempt] = {}
        self.enrollment: Enrollment | None = None

    def status(self) -> dict:
        return {
            "version": "0.5.0",
            "mode": "sandbox",
            "token": self.token,
            "engine": {"ready": self.engine is not None, "id": MODEL_ID, "message": self.engine_error},
            "profile": self.store.public(),
            "storage": self.store.label,
            "storage_error": self.store.error,
            "threshold": DEFAULT_THRESHOLD,
            "liveness": "blink-and-open-eyes",
            "camera_pipeline": "buffered-v1",
        }

    def score(self, observation) -> float | None:
        if observation.embedding is None or self.store.profile is None:
            return None
        return profile_similarity(observation.embedding, self.store.profile)

    def observe(self, data: dict, skip_recognition=None):
        if self.engine is None:
            raise ApiError(self.engine_error or "Recognition engine is unavailable.", 503)
        return self.engine.observe(decode_image(data.get("image")), skip_recognition=skip_recognition)

    def save_profile(self, name: str, embeddings: list, source: str, poses: list | None = None):
        self.store.save({
            "id": secrets.token_hex(12), "name": name.strip(), "model_id": MODEL_ID,
            "embedding": normalized(np.mean(embeddings, axis=0)).tolist(),
            "templates": [normalized(embedding).tolist() for embedding in embeddings],
            "samples": len(embeddings), "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "guided": poses is not None, "poses": poses or [],
        })
        self.attempts.clear()
        self.enrollment = None
        return self.status()

    def enrollment_name(self, data: dict) -> str:
        if self.store.profile or self.store.error:
            raise ApiError("Remove the existing profile before enrolling again.", 409)
        name = data.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ApiError("Enter a profile name between 1 and 40 characters.")
        return name.strip()

    def attempt_frames(self, attempt: Attempt, data: dict) -> dict:
        """Bounded, ordered camera samples; eye/identity evidence is always measured.

        Offsets use the browser's monotonic capture clock relative to starting the
        attempt. They preserve blink duration across HTTP batching, with a small
        allowance for initial request transit. This sandbox cannot attest cameras.
        """
        received = monotonic()
        if received - attempt.started_at > 20:
            return {"observation": Observation(0, "Test expired.").public(),
                    "attempt": attempt.observe(None, now=received)}
        frames = data.get("frames")
        if attempt.source != "camera" or not isinstance(frames, list) or not 1 <= len(frames) <= 6:
            raise ApiError("Send between one and six camera frames.")
        previous = attempt.last_capture_ms
        for frame in frames:
            offset = frame.get("offset_ms") if isinstance(frame, dict) else None
            if (isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset)
                    or offset < 0 or offset <= previous):
                raise ApiError("Camera samples must have increasing capture times.")
            age = received - (attempt.started_at + offset / 1000)
            if not -.25 <= age <= .75:
                attempt.reset("Camera frames were delayed. Look at the camera again.")
                raise ApiError("Camera frames are stale. Stop the test and try again.", 409)
            previous = offset
        for index, frame in enumerate(frames):
            phase = attempt.phase
            captured = attempt.started_at + frame["offset_ms"] / 1000
            observation = self.observe(frame, skip_recognition=lambda attention, box: attempt.can_track_open_eyes(attention, box, captured))
            if observation.identity_checked:
                score = self.score(observation)
            else:
                score = attempt.last_identity_score
            attempt.last_capture_ms = frame["offset_ms"]
            result = attempt.observe(score, now=captured,
                                     attention=observation.attention, latest=index == len(frames) - 1,
                                     box=observation.box, identity_checked=observation.identity_checked)
            # Send the prompt before processing any more images. Already-buffered
            # images cannot answer a challenge the user has not seen yet.
            if phase == "identity" and attempt.phase == "blink":
                break
            if result["state"] != "scanning":
                break
        return {"observation": observation.public(score), "attempt": result}

    def dispatch(self, method: str, path: str, data: dict | None = None) -> dict:
        # OpenCV models and the profile/attempt state have one serialized owner.
        with self.lock:
            try:
                return self._dispatch(method, path, data or {})
            except InputError as error:
                raise ApiError(str(error)) from error

    def _dispatch(self, method: str, path: str, data: dict) -> dict:
        if method == "GET" and path == "/api/status":
            return self.status()
        if method == "DELETE" and path == "/api/profile":
            self.store.clear()
            self.attempts.clear()
            self.enrollment = None
            return self.status()
        if method == "POST" and path == "/api/analyze":
            observation = self.observe(data)
            return observation.public(self.score(observation))
        if method == "POST" and path == "/api/enroll":
            name = self.enrollment_name(data)
            images = data.get("images")
            source = data.get("source")
            if source != "image":
                raise ApiError("Camera enrollment requires the guided pose sequence.")
            if not isinstance(images, list) or not 1 <= len(images) <= 5:
                raise ApiError("Image enrollment needs 1 to 5 samples.")
            observations = [self.observe({"image": image}) for image in images]
            for index, observation in enumerate(observations):
                if observation.embedding is None:
                    raise ApiError(f"Sample {index + 1}: {observation.message}")
                if observation.attention is None or observation.attention.eyes != "open":
                    raise ApiError(f"Sample {index + 1}: both eyes must be open and visible.")
            embeddings = [observation.embedding for observation in observations]
            for index, embedding in enumerate(embeddings):
                if any(similarity(embedding, other) < 0.5 for other in embeddings[:index]):
                    raise ApiError("Samples do not consistently match one face. Try again with small changes in angle.")
            return self.save_profile(name, embeddings, source)
        if method == "POST" and path == "/api/enrollments":
            name = self.enrollment_name(data)
            self.enrollment = Enrollment(secrets.token_hex(16), name, monotonic())
            self.attempts.clear()
            return self.enrollment.public()
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "enrollments"]:
            enrollment = self.enrollment
            if enrollment is None or enrollment.id != parts[2]:
                raise ApiError("This enrollment has ended. Start again.", 404)
            if method == "DELETE" and len(parts) == 3:
                self.enrollment = None
                return {"state": "canceled"}
            if method == "POST" and len(parts) == 4:
                if enrollment.expire(monotonic()):
                    raise ApiError(enrollment.message, 409)
                if parts[3] == "frame":
                    observation = self.observe(data)
                    result = enrollment.observe(observation)
                    return {"observation": observation.public(), "enrollment": result}
                if parts[3] == "finish":
                    if enrollment.state != "ready" or len(enrollment.embeddings) != 5:
                        raise ApiError("Complete all five guided angles first.", 409)
                    if self.store.profile or self.store.error:
                        raise ApiError("The profile changed. Start again.", 409)
                    return self.save_profile(enrollment.name, enrollment.embeddings, "camera", enrollment.poses)
        if method == "POST" and path == "/api/attempts":
            if not self.store.profile:
                raise ApiError("Enroll a face before starting a test.", 409)
            source = data.get("source")
            threshold = data.get("threshold", DEFAULT_THRESHOLD)
            if source not in ("camera", "image"):
                raise ApiError("Choose camera or image testing.")
            if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0.35 <= threshold <= 0.9:
                raise ApiError("Threshold must be between 0.35 and 0.90.")
            # New attempts invalidate earlier scans, including scans in other tabs.
            self.attempts.clear()
            self.enrollment = None
            attempt = Attempt(secrets.token_hex(16), self.store.profile["id"], source, threshold, monotonic())
            self.attempts[attempt.id] = attempt
            return attempt.public()
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "attempts"]:
            attempt = self.attempts.get(parts[2])
            if attempt is None:
                raise ApiError("This test has ended. Start a new test.", 404)
            if method == "DELETE" and len(parts) == 3:
                del self.attempts[attempt.id]
                return {"state": "locked"}
            if method == "POST" and len(parts) == 4 and parts[3] == "frame":
                if not self.store.profile or self.store.profile["id"] != attempt.profile_id:
                    raise ApiError("The enrolled profile changed. Start a new test.", 409)
                observation = self.observe(data)
                score = self.score(observation)
                result = attempt.observe(score, attention=observation.attention, box=observation.box)
                return {"observation": observation.public(score), "attempt": result}
            if method == "POST" and len(parts) == 4 and parts[3] == "frames":
                if not self.store.profile or self.store.profile["id"] != attempt.profile_id:
                    raise ApiError("The enrolled profile changed. Start a new test.", 409)
                return self.attempt_frames(attempt, data)
        raise ApiError("Endpoint not found.", 404)
