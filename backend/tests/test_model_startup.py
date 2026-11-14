import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from backend.viso.attention import AttentionEngine
from backend.viso.recognition import FaceEngine


class ModelStartupTests(unittest.TestCase):
    def test_verified_model_bytes_are_read_once_and_passed_to_native_engines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {name: name.encode() for name in (
                "face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx", "face_landmarker.task")}
            for name, payload in files.items():
                (root / name).write_bytes(payload)
            (root / "manifest.json").write_text(json.dumps({"models": [
                {"file": name, "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in files.items()]}))
            original = Path.read_bytes
            reads = []
            def read(path):
                reads.append(path.name)
                return original(path)
            with patch.object(Path, "read_bytes", read), \
                    patch("backend.viso.recognition.cv2.FaceDetectorYN.create") as detector, \
                    patch("backend.viso.recognition.cv2.FaceRecognizerSF.create") as recognizer, \
                    patch("backend.viso.recognition.AttentionEngine") as attention:
                engine = FaceEngine(root)
                self.assertCountEqual(reads, files)
                self.assertEqual(detector.call_args.args[1].tobytes(), files["face_detection_yunet_2023mar.onnx"])
                self.assertEqual(recognizer.call_args.args[1].tobytes(), files["face_recognition_sface_2021dec.onnx"])
                attention.assert_called_once_with(root, files["face_landmarker.task"])
                engine.close()
            (root / "face_landmarker.task").write_bytes(b"corrupted")
            with patch("backend.viso.recognition.cv2.FaceDetectorYN.create") as detector, self.assertRaisesRegex(RuntimeError, "checksum failed"):
                FaceEngine(root)
            detector.assert_not_called()

    def test_warmup_uses_only_blank_inputs_and_creates_no_authentication_evidence(self):
        engine = FaceEngine.__new__(FaceEngine)
        engine.detector, engine.recognizer, engine.attention = Mock(), Mock(), Mock()
        engine.warmup()
        engine.detector.setInputSize.assert_called_once_with((320, 320))
        for image in (engine.detector.detect.call_args.args[0], engine.recognizer.feature.call_args.args[0]):
            self.assertEqual(image.dtype, np.uint8)
            self.assertFalse(image.any())
        engine.attention.warmup.assert_called_once_with()
        self.assertEqual(set(engine.__dict__), {"detector", "recognizer", "attention"})

    def test_attention_warmup_uses_blank_rgb_without_eye_or_pose_evidence(self):
        engine = AttentionEngine.__new__(AttentionEngine)
        engine.mp, engine.landmarker = Mock(), Mock()
        engine.warmup()
        image = engine.mp.Image.call_args.kwargs
        self.assertEqual(image["image_format"], engine.mp.ImageFormat.SRGB)
        self.assertEqual(image["data"].shape, (320, 320, 3))
        self.assertEqual(image["data"].dtype, np.uint8)
        self.assertFalse(image["data"].any())
        engine.landmarker.detect.assert_called_once_with(engine.mp.Image.return_value)
        self.assertEqual(set(engine.__dict__), {"mp", "landmarker"})
