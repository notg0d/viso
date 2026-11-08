"""CPU-only ONNX inference. Camera frames are processed in memory."""

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "16777216")

import cv2
import numpy as np

from .attention import Attention, AttentionEngine

MODEL_ID = "sface-2021dec-yunet-2023mar-v1"
DEFAULT_THRESHOLD = 0.55


class InputError(ValueError):
    pass


def normalized(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(vector).all() or norm < 1e-8:
        raise InputError("Invalid face embedding.")
    return vector / norm


def similarity(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.clip(np.dot(normalized(first), normalized(second)), -1, 1))


def decode_image(value: str) -> np.ndarray:
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

    def public(self, score: float | None = None) -> dict:
        return {
            "face_count": self.face_count,
            "usable": self.embedding is not None,
            "message": self.message,
            "box": self.box,
            "detection_score": self.detection_score,
            "latency_ms": round(self.latency_ms, 1),
            "similarity": round(score, 4) if score is not None else None,
            "attention": (self.attention or Attention()).public(),
        }


class FaceEngine:
    def __init__(self, model_dir: Path):
        manifest = json.loads((model_dir / "manifest.json").read_text())
        for model in manifest["models"]:
            path = model_dir / model["file"]
            if not path.exists():
                raise RuntimeError("Models are missing. Run .\\scripts\\setup.ps1.")
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != model["sha256"]:
                    raise RuntimeError(f"Model checksum failed: {path.name}. Re-run setup.")
        cv2.setNumThreads(min(os.cpu_count() or 2, 4))
        self.detector = cv2.FaceDetectorYN.create(
            str(model_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.85, 0.3, 1000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(model_dir / "face_recognition_sface_2021dec.onnx"), ""
        )
        self.attention = AttentionEngine(model_dir)

    def close(self):
        self.attention.close()

    def observe(self, image: np.ndarray) -> Observation:
        start = perf_counter()
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)
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
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if brightness < 30 or brightness > 235:
                    result = Observation(1, "Use more even lighting on your face.", box=box)
                elif sharpness < 20:
                    result = Observation(1, "Hold still: the face image is too blurry.", box=box)
                else:
                    embedding = normalized(self.recognizer.feature(aligned))
                    result = Observation(1, "Face ready", embedding, box, float(face[-1]))
                    result.attention = self.attention.observe(image, face)
        result.latency_ms = (perf_counter() - start) * 1000
        return result
