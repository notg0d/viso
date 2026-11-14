"""CPU-only ONNX inference. Camera frames are processed in memory."""

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "16777216")

import cv2
import numpy as np

from .attention import Attention, AttentionEngine
from .lighting import measure_lighting

MODEL_ID = "sface-2021dec-yunet-2023mar-v1"
DEFAULT_THRESHOLD = 0.55


class InputError(ValueError):
    pass


def normalized(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or not np.isfinite(norm) or norm < 1e-8:
        raise InputError("Invalid face embedding.")
    return vector / norm


def similarity(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.clip(np.dot(normalized(first), normalized(second)), -1, 1))


def profile_similarity(embedding: np.ndarray, profile: dict) -> float:
    return ProfileMatcher(profile).score(embedding)


class ProfileMatcher:
    """Compile normalized float32 views once; no profile-sized frame allocations.

    Two repeated samples from one pose are one vote, not independent evidence.
    Legacy profiles retain their original centroid/two-view rule.
    """
    def __init__(self, profile: dict):
        self.centroid = normalized(profile["embedding"])
        templates = profile.get("templates", [])
        self.views = np.stack([normalized(view) for view in templates]) if len(templates) >= 2 else None
        groups = profile.get("template_groups")
        if groups is not None and (not isinstance(groups, list) or len(groups) != len(templates)
                                   or any(not isinstance(group, str) for group in groups)):
            raise InputError("Invalid enrollment pose groups.")
        self.group_starts = None
        if groups is not None and self.views is not None:
            labels = {group: index for index, group in enumerate(dict.fromkeys(groups))}
            numbers = np.asarray([labels[group] for group in groups])
            order = np.argsort(numbers, kind="stable")
            self.views = np.ascontiguousarray(self.views[order])
            self.group_starts = np.flatnonzero(np.r_[True, np.diff(numbers[order]) != 0])

    def score(self, embedding: np.ndarray) -> float:
        probe = normalized(embedding)
        score = float(np.dot(probe, self.centroid))
        if self.views is not None:
            scores = self.views @ probe
            if self.group_starts is not None:
                scores = np.maximum.reduceat(scores, self.group_starts)
            if len(scores) >= 2:
                score = max(score, float(np.partition(scores, -2)[-2]))
        return float(np.clip(score, -1, 1))


def decode_image(value: str | np.ndarray) -> np.ndarray:
    # ndarrays can only come from the in-process native camera; JSON inputs still
    # take the bounded JPEG/PNG path below.
    if isinstance(value, np.ndarray):
        if value.dtype != np.uint8 or value.ndim != 3 or value.shape[2] != 3 or min(value.shape[:2]) < 80 or max(value.shape[:2]) > 960:
            raise InputError("Invalid native camera frame.")
        return value
    if not isinstance(value, str) or len(value) > 3_000_000:
        raise InputError("Choose a JPEG or PNG image smaller than 2 MB after resizing.")
    header, separator, encoded = value.partition(",")
    if not separator or header not in ("data:image/jpeg;base64", "data:image/png;base64"):
        raise InputError("Expected a JPEG or PNG image.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (binascii.Error, cv2.error, ValueError) as error:
        raise InputError("The image could not be decoded.") from error
    if image is None:
        raise InputError("The image could not be decoded.")
    height, width = image.shape[:2]
    if min(height, width) < 80 or max(height, width) > 4096:
        raise InputError("Image dimensions must be between 80 and 4096 pixels.")
    if max(height, width) > 960:
        image = cv2.resize(image, (round(width * 960 / max(height, width)), round(height * 960 / max(height, width))))
    return image


@dataclass
class Observation:
    face_count: int
    message: str
    embedding: np.ndarray | None = None
    box: list[float] | None = None
    detection_score: float | None = None
    latency_ms: float = 0
    attention: Attention | None = None
    identity_checked: bool = True
    lighting: dict | None = None

    def public(self, score: float | None = None) -> dict:
        return {
            "face_count": self.face_count,
            "usable": self.embedding is not None or not self.identity_checked,
            "message": self.message,
            "box": self.box,
            "detection_score": self.detection_score,
            "latency_ms": round(self.latency_ms, 1),
            "similarity": round(score, 4) if score is not None else None,
            "attention": (self.attention or Attention()).public(),
            "identity_checked": self.identity_checked,
            "lighting": self.lighting,
        }


class FaceEngine:
    def __init__(self, model_dir: Path):
        manifest = json.loads((model_dir / "manifest.json").read_text())
        payloads = {}
        for model in manifest["models"]:
            path = model_dir / model["file"]
            if not path.exists():
                raise RuntimeError("Models are missing. Extract the entire Viso release ZIP, or run scripts\\setup.ps1 in a source checkout.")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != model["sha256"]:
                raise RuntimeError(f"Model checksum failed: {path.name}. Extract a verified Viso release ZIP again, or re-run source setup.")
            payloads[model["file"]] = payload
        cv2.setNumThreads(min(os.cpu_count() or 2, 4))
        # OpenCV's filename overload uses narrow Windows paths. Python reads
        # Unicode paths correctly; the buffer overload keeps models in memory.
        empty_config = np.empty(0, dtype=np.uint8)
        self.detector = cv2.FaceDetectorYN.create(
            "onnx", np.frombuffer(payloads.pop("face_detection_yunet_2023mar.onnx"), dtype=np.uint8),
            empty_config, (320, 320), 0.85, 0.3, 1000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            "onnx", np.frombuffer(payloads.pop("face_recognition_sface_2021dec.onnx"), dtype=np.uint8), empty_config
        )
        self.attention = AttentionEngine(model_dir, payloads.pop("face_landmarker.task"))

    def warmup(self):
        """Initialize native inference on blank inputs, never camera/profile data."""
        self.detector.setInputSize((320, 320))
        self.detector.detect(np.zeros((320, 320, 3), dtype=np.uint8))
        self.recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
        self.attention.warmup()

    def close(self):
        if self.attention is not None:
            self.attention.close()
        self.attention = self.detector = self.recognizer = None

    def observe(self, image: np.ndarray, skip_recognition: Callable[[Attention, list[float]], bool] | None = None) -> Observation:
        start = perf_counter()
        lighting = measure_lighting(image)
        height, width = image.shape[:2]
        # Detection needs far fewer pixels than eye geometry/recognition. Keep the
        # original image for both, and map all five YuNet landmarks back to it.
        scale = min(1.0, 320 / max(width, height))
        small = cv2.resize(image, (round(width * scale), round(height * scale))) if scale < 1 else image
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        if faces is not None:
            faces[:, :14:2] *= width / small.shape[1]
            faces[:, 1:14:2] *= height / small.shape[0]
        count = 0 if faces is None else len(faces)
        if count != 1:
            result = Observation(count, "No face detected. Face the camera in good light." if count == 0 else "Keep only one face in the frame.")
        else:
            face = faces[0]
            x, y, w, h = map(float, face[:4])
            box = [max(0.0, x / width), max(0.0, y / height), min(w / width, 1.0), min(h / height, 1.0)]
            if min(w, h) < 70:
                result = Observation(1, "Move closer: your face is too small to enroll or match.", box=box)
            elif x < -w * 0.1 or y < -h * 0.1 or x + w > width + w * 0.1 or y + h > height + h * 0.1:
                result = Observation(1, "Center your whole face in the frame.", box=box)
            else:
                aligned = self.recognizer.alignCrop(image, face)
                gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                brightness = float(gray.mean())
                lighting = measure_lighting(aligned, "face")
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if brightness < 30 or brightness > 235:
                    result = Observation(1, "Use more even lighting on your face.", box=box)
                elif sharpness < 20:
                    result = Observation(1, "Hold still: the face image is too blurry.", box=box)
                else:
                    attention = self.attention.observe(image, face)
                    skip = skip_recognition is not None and skip_recognition(attention, box)
                    embedding = None if skip else normalized(self.recognizer.feature(aligned))
                    result = Observation(1, "Face ready", embedding, box, float(face[-1]),
                                         attention=attention, identity_checked=not skip)
        result.lighting = lighting
        result.latency_ms = (perf_counter() - start) * 1000
        return result
