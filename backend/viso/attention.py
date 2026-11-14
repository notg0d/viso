"""Per-frame eye state and head pose; no temporal state shared between people."""

from dataclasses import asdict, dataclass
from math import atan2, degrees, hypot
from pathlib import Path

import cv2
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
    left_raw_ear: float | None = None
    right_raw_ear: float | None = None
    eye_method: str = "measured"

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
    """Identity-local strict-open references; inferred open states never train it."""

    def __init__(self):
        self.samples: list[tuple[float, float, float, float]] = []
        self.poses: list[tuple | None] = []

    def classify(self, attention: Attention, calibrating: bool = False) -> str:
        values = (attention.left_blink, attention.right_blink, attention.left_ear, attention.right_ear)
        if any(value is None for value in values) or not np.isfinite(values).all():
            return attention.eyes
        if attention.eyes == "unknown":
            return "unknown"
        pose = (attention.yaw, attention.pitch, attention.roll)
        pose = pose if all(value is not None for value in pose) and np.isfinite(pose).all() else None
        if attention.eyes == "open" and attention.eye_method == "measured" and calibrating and eye_state(*values) == "open":
            self.samples = (self.samples + [values])[-12:]
            self.poses = (self.poses + [pose])[-12:]
        if attention.eyes in ("open", "closed") or len(self.samples) < 3:
            return attention.eyes
        left, right, left_ear, right_ear = values
        # A head turn must not masquerade as the geometry drop of a blink.
        nearby = [sample for sample, reference in zip(self.samples, self.poses)
                  if (pose is None and reference is None) or (pose is not None and reference is not None
                      and max(abs(a - b) for a, b in zip(pose, reference)) <= 10)]
        if len(nearby) >= 3:
            base_left, base_right, base_left_ear, base_right_ear = np.median(nearby, axis=0)
            if (left >= max(.35, base_left + .20) and right >= max(.35, base_right + .20)
                    and left_ear <= min(.21, base_left_ear * .72)
                    and right_ear <= min(.21, base_right_ear * .72)):
                return "closed"
        # Chin-up views can bias the blendshapes even after geometry is corrected.
        # Permit only a bounded coefficient change while BOTH apertures retain at
        # least 90% of a strict-open reference. No reference, no relaxed decision.
        if pose is not None and -35 <= pose[1] <= -8 and abs(pose[0]) <= 25 and abs(pose[2]) <= 20:
            references = [sample for sample, reference in zip(self.samples, self.poses)
                          if reference is not None and abs(pose[0] - reference[0]) <= 12
                          and abs(pose[1] - reference[1]) <= 22 and abs(pose[2] - reference[2]) <= 12]
            raw = (attention.left_raw_ear, attention.right_raw_ear)
            if len(references) >= 3 and all(value is not None for value in raw) and np.isfinite(raw).all() and min(raw) >= .14:
                bl, br, el, er = np.median(references, axis=0)
                if (0 <= left <= min(.45, bl + .15) and 0 <= right <= min(.45, br + .15)
                        and left_ear >= max(.18, el * .90) and right_ear >= max(.18, er * .90)):
                    return "open"
        return "uncertain"


def apply_eye_state(attention: Attention, state: str):
    if state == attention.eyes:
        return
    attention.eye_method = "pose-calibrated" if state == "open" else "relative-blink"
    attention.eyes = state
    attention.message = {"open": "Both eyes open", "closed": "Both eyes closed — reopen your eyes",
                         "uncertain": "Open both eyes fully; keep them visible.",
                         "unknown": "Keep both eyes visible in good light."}[state]


def eye_geometry(points: np.ndarray, rotation: np.ndarray, indices: list[int], size: tuple[int, int]) -> tuple[float, float]:
    """Return screen EAR and bounded head-local EAR from MediaPipe XYZ pixels.

    MediaPipe normalized Z uses the image WIDTH, not height. Convert screen axes
    to the metric camera axes before undoing head rotation. Project onto the
    local eye plane so depth separation alone cannot count as an open eyelid.
    """
    eye = points[indices]
    width = np.linalg.norm(eye[0, :2] - eye[3, :2])
    if (not np.isfinite(eye).all() or width < 12 or np.any(eye[:, :2] < 0)
            or np.any(eye[:, :2] >= size)):
        return float("nan"), float("nan")
    raw = float((np.linalg.norm(eye[1, :2] - eye[5, :2]) + np.linalg.norm(eye[2, :2] - eye[4, :2])) / (2 * width))
    local = (eye * [1, -1, -1]) @ rotation
    a, b, c, d, e, f = local[:, :2]
    local_width = np.linalg.norm(a - d)
    if local_width < 12 or not np.isfinite(local).all():
        return float("nan"), float("nan")
    # Keep the established near-frontal measurement; compensate foreshortening
    # only, with a 25% cap. Tiny screen apertures still fail the raw-open floor.
    corrected = float((np.linalg.norm(b - f) + np.linalg.norm(c - e)) / (2 * local_width))
    return raw, min(max(raw, corrected), raw * 1.25)


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
    def __init__(self, model_dir: Path, model_buffer: bytes | None = None):
        # Profile validation and non-camera commands do not need MediaPipe.
        import mediapipe as mp
        self.mp = mp
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=model_buffer if model_buffer is not None else (model_dir / "face_landmarker.task").read_bytes()),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                num_faces=2,
                min_face_detection_confidence=.65,
                min_face_presence_confidence=.65,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
        )

    def warmup(self):
        # IMAGE mode has no temporal tracking; no eye references are created here.
        self.landmarker.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                                             data=np.zeros((320, 320, 3), dtype=np.uint8)))

    def close(self):
        self.landmarker.close()

    def observe(self, image: np.ndarray, face: np.ndarray) -> Attention:
        mp = self.mp
        result = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
        if len(result.face_landmarks) != 1 or len(result.face_blendshapes) != 1 or len(result.facial_transformation_matrixes) != 1:
            return Attention()
        points = np.array([(point.x * image.shape[1], point.y * image.shape[0], point.z * image.shape[1]) for point in result.face_landmarks[0]])
        # Associate both models with the same face, not merely a face somewhere in the image.
        if not np.isfinite(points).all() or np.linalg.norm(points[1, :2] - face[8:10]) > face[2] * .25:
            return Attention()
        matrix = np.asarray(result.facial_transformation_matrixes[0], dtype=float)
        if matrix.shape != (4, 4):
            return Attention()
        rotation = matrix[:3, :3]
        norms = np.linalg.norm(rotation, axis=0)
        if not np.isfinite(matrix).all() or np.any(norms < 1e-6):
            return Attention()
        rotation = rotation / norms
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=.03) or np.linalg.det(rotation) < .95:
            return Attention()
        size = (image.shape[1], image.shape[0])
        left_raw, left_ear = eye_geometry(points, rotation, [362, 385, 387, 263, 373, 380], size)
        right_raw, right_ear = eye_geometry(points, rotation, [33, 160, 158, 133, 153, 144], size)
        scores = {item.category_name: item.score for item in result.face_blendshapes[0]}
        left, right = scores.get("eyeBlinkLeft", float("nan")), scores.get("eyeBlinkRight", float("nan"))
        yaw, pitch, roll = head_angles(matrix)
        if not np.isfinite([left, right, left_ear, right_ear, yaw, pitch, roll]).all():
            return Attention()
        state = eye_state(left, right, left_ear, right_ear)
        if state == "open" and min(left_raw, right_raw) < .14:
            state = "uncertain"
        message = {"open": "Both eyes open", "closed": "Both eyes closed — reopen your eyes", "uncertain": "Open both eyes fully; keep them visible.", "unknown": "Keep both eyes visible in good light."}[state]
        if abs(yaw) > 35 or abs(pitch) > 35 or abs(roll) > 25:
            state, message = "unknown", "Face the camera more directly so both eyes can be checked."
        return Attention(state, left, right, left_ear, right_ear, yaw, pitch, roll, message, left_raw, right_raw)
