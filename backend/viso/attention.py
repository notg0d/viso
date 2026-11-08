"""Per-frame eye state and head pose; no temporal state shared between people."""

from dataclasses import asdict, dataclass
from math import atan2, degrees, hypot
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


@dataclass
class Attention:
    eyes: str = "unknown"
    left_blink: float | None = None
    right_blink: float | None = None
    left_ear: float | None = None
    right_ear: float | None = None
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    message: str = "Keep both eyes visible in good light."

    def public(self) -> dict:
        return {key: round(value, 3) if isinstance(value, float) else value for key, value in asdict(self).items()}


def eye_state(left: float, right: float, left_ear: float, right_ear: float) -> str:
    if not np.isfinite([left, right, left_ear, right_ear]).all():
        return "unknown"
    if min(left, right) < 0 or max(left, right) > 1 or min(left_ear, right_ear) <= 0:
        return "unknown"
    # Keep the open-eye gate strict. Closure is also checked relative to the
    # current person's open-eye geometry by EyeCalibration during an attempt.
    if max(left, right) <= .30 and min(left_ear, right_ear) >= .18:
        return "open"
    if min(left, right) >= .60 and max(left_ear, right_ear) <= .21:
        return "closed"
    return "uncertain"


def open_measurement_jitter(attention: Attention) -> bool:
    """Near-cutoff uncertainty may pause tracking, but never counts as open."""
    values = (attention.left_blink, attention.right_blink, attention.left_ear, attention.right_ear)
    if attention.eyes != "uncertain" or any(value is None for value in values) or not np.isfinite(values).all():
        return False
    left, right, left_ear, right_ear = values
    return 0 <= min(left, right) and .30 < max(left, right) <= .34 and min(left_ear, right_ear) >= .18


class EyeCalibration:
    """Attempt-local baseline: a quick, bilateral geometry drop can be a blink.

    Only already-confirmed open eyes train it. It never makes the open-eye gate
    more permissive and is discarded on lost/changed identity or tracking.
    """

    def __init__(self):
        self.samples: list[tuple[float, float, float, float]] = []

    def classify(self, attention: Attention, calibrating: bool = False) -> str:
        values = (attention.left_blink, attention.right_blink, attention.left_ear, attention.right_ear)
        if any(value is None for value in values) or not np.isfinite(values).all():
            return attention.eyes
        if attention.eyes == "unknown":
            return "unknown"
        if attention.eyes == "open" and calibrating:
            self.samples = (self.samples + [values])[-12:]
        if attention.eyes in ("open", "closed") or len(self.samples) < 3:
            return attention.eyes
        left, right, left_ear, right_ear = values
        base_left, base_right, base_left_ear, base_right_ear = np.median(self.samples, axis=0)
        if (left >= max(.35, base_left + .20) and right >= max(.35, base_right + .20)
                and left_ear <= min(.21, base_left_ear * .72)
                and right_ear <= min(.21, base_right_ear * .72)):
            return "closed"
        return "uncertain"


def head_angles(matrix: np.ndarray) -> tuple[float, float, float]:
    rotation = np.asarray(matrix, dtype=float)[:3, :3]
    rotation = rotation / np.linalg.norm(rotation, axis=0)
    # MediaPipe's right-handed metric camera: +Y up, +Z toward the viewer.
    # Positive yaw = subject's left; positive pitch = chin down.
    yaw = degrees(atan2(-rotation[2, 0], hypot(rotation[0, 0], rotation[1, 0])))
    pitch = degrees(atan2(rotation[2, 1], rotation[2, 2]))
    roll = degrees(atan2(rotation[1, 0], rotation[0, 0]))
    return yaw, pitch, roll


class AttentionEngine:
    def __init__(self, model_dir: Path):
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_dir / "face_landmarker.task")),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                num_faces=2,
                min_face_detection_confidence=.65,
                min_face_presence_confidence=.65,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
        )

    def close(self):
        self.landmarker.close()

    def observe(self, image: np.ndarray, face: np.ndarray) -> Attention:
        result = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
        if len(result.face_landmarks) != 1 or len(result.face_blendshapes) != 1 or len(result.facial_transformation_matrixes) != 1:
            return Attention()
        points = np.array([(point.x * image.shape[1], point.y * image.shape[0]) for point in result.face_landmarks[0]])
        # Associate both models with the same face, not merely a face somewhere in the image.
        if not np.isfinite(points).all() or np.linalg.norm(points[1] - face[8:10]) > face[2] * .25:
            return Attention()

        def ear(indices):
            a, b, c, d, e, f = points[indices]
            width = np.linalg.norm(a - d)
            if width < 12 or np.any(points[indices] < 0) or np.any(points[indices] >= [image.shape[1], image.shape[0]]):
                return float("nan")
            return float((np.linalg.norm(b - f) + np.linalg.norm(c - e)) / (2 * width))

        left_ear = ear([362, 385, 387, 263, 373, 380])
        right_ear = ear([33, 160, 158, 133, 153, 144])
        scores = {item.category_name: item.score for item in result.face_blendshapes[0]}
        left, right = scores.get("eyeBlinkLeft", float("nan")), scores.get("eyeBlinkRight", float("nan"))
        yaw, pitch, roll = head_angles(result.facial_transformation_matrixes[0])
        if not np.isfinite([left, right, left_ear, right_ear, yaw, pitch, roll]).all():
            return Attention()
        state = eye_state(left, right, left_ear, right_ear)
        message = {"open": "Both eyes open", "closed": "Both eyes closed — reopen your eyes", "uncertain": "Open both eyes fully; keep them visible.", "unknown": "Keep both eyes visible in good light."}[state]
        if abs(yaw) > 35 or abs(pitch) > 35 or abs(roll) > 25:
            state, message = "unknown", "Face the camera more directly so both eyes can be checked."
        return Attention(state, left, right, left_ear, right_ear, yaw, pitch, roll, message)
