"""Native transport/capture boundary tests, in addition to the recognition suite."""

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from backend.tests.test_liveness import observation
from backend.tests.test_sandbox import profile
from backend.viso.native import Camera, NativeHost
from backend.viso.service import ApiError, SandboxService
from backend.viso.storage import ProfileStore


class FakeCamera:
    def __init__(self):
        self.samples = []
        self.stopped = False

    def frame(self):
        if self.stopped:
            raise ApiError("No fresh frame.")
        return "test-frame"

    def take(self, after):
        samples, self.samples = self.samples, []
        return [sample for sample in samples if sample[0] > after]

    def discard(self):
        self.samples.clear()

    def stop(self):
        self.stopped = True
        self.discard()


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ProfileStore(Path(self.directory.name), ephemeral=True)
        self.store.save(profile())
        self.service = SandboxService(None, self.store)
        self.camera = FakeCamera()
        self.host = NativeHost(self.service, self.camera)

    def start(self):
        with patch("backend.viso.service.monotonic", return_value=100):
            return self.host.handle("attempt.start", {"threshold": .55})

    def tick(self, times, observations, now):
        self.camera.samples = [(time, "test") for time in times]
        with patch("backend.viso.native.monotonic", return_value=now), \
                patch("backend.viso.service.monotonic", return_value=now), \
                patch.object(self.service, "observe", side_effect=observations):
            return self.host.handle("attempt.tick", {})

    def test_prompt_ack_drops_buffered_closures_and_allows_only_fresh_blink(self):
        self.start()
        result = self.tick([100.1, 100.2, 100.3, 100.35], [observation()] * 4, 100.4)
        self.assertTrue(result["prompt_pending"])
        self.assertEqual(result["attempt"]["phase"], "blink")
        self.camera.samples = [(100.42, "closed-before-prompt")]
        with patch("backend.viso.native.monotonic", return_value=100.45), patch.object(self.service, "observe") as observe:
            self.assertTrue(self.host.handle("attempt.tick", {})["prompt_pending"])
            observe.assert_not_called()
            self.host.handle("attempt.ack", {})
        self.assertFalse(self.camera.samples)
        result = self.tick([100.5, 100.55, 100.6, 100.75], [observation(), observation("closed"), observation(), observation()], 100.8)
        self.assertEqual(result["attempt"]["state"], "unlocked")

    def test_camera_stop_revokes_active_attempt(self):
        result = self.start()
        self.host.handle("camera.stop", {})
        self.assertTrue(self.camera.stopped)
        self.assertNotIn(result["attempt"]["id"], self.service.attempts)
        with self.assertRaises(ApiError):
            self.host.handle("attempt.tick", {})

    def test_cancel_discards_incomplete_enrollment_without_saving(self):
        self.store.clear()
        self.host.handle("enrollment.start", {"name": "Zoë 李"})
        self.assertEqual(self.service.enrollment.name, "Zoë 李")
        with self.assertRaises(ApiError):
            self.host.handle("enrollment.finish", {})
        self.host.handle("cancel", {})
        self.assertIsNone(self.store.profile)
        self.assertIsNone(self.service.enrollment)
        with self.assertRaises(ApiError):
            self.host.handle("enrollment.finish", {})

    def test_profile_deletion_revokes_attempt_and_status_hides_vectors(self):
        self.start()
        status = self.host.handle("status", {})
        self.assertNotIn("token", status)
        self.assertNotIn("embedding", status["profile"])
        self.assertNotIn("templates", status["profile"])
        self.host.handle("profile.delete", {})
        self.assertFalse(self.service.attempts)
        self.assertIsNone(self.store.profile)

    def test_still_image_cannot_unlock_and_attempt_is_disposed(self):
        with patch.object(self.service, "observe", return_value=observation()):
            result = self.host.handle("image.test", {"image": "test", "threshold": .35})
        self.assertNotEqual(result["attempt"]["state"], "unlocked")
        self.assertFalse(self.service.attempts)

    def test_expiry_is_enforced_while_waiting_for_prompt_ack(self):
        result = self.start()
        self.host.awaiting_prompt = True
        with patch("backend.viso.native.monotonic", return_value=121), patch("backend.viso.sessions.monotonic", return_value=121):
            result = self.host.handle("attempt.tick", {})
        self.assertEqual(result["attempt"]["state"], "expired")

    def test_camera_queue_is_bounded_fresh_ordered_and_cleared(self):
        camera = Camera(lambda message: None)
        for stamp in [99, 99.8, 99.9, 100, 100.1, 100.2, 100.3, 100.4]:
            camera.frames.append((stamp, str(stamp)))
        with patch("backend.viso.native.monotonic", return_value=100.5):
            samples = camera.take(100)
        self.assertEqual([time for time, _ in samples], [100.1, 100.2, 100.3, 100.4])
        self.assertFalse(camera.frames)

    def test_native_capture_rejects_stale_frame_and_driver_errors(self):
        camera = Camera(lambda message: None)
        camera.latest = (100, "image")
        with patch("backend.viso.native.monotonic", return_value=101):
            with self.assertRaises(ApiError):
                camera.frame()
        camera.error = "Disconnected"
        with self.assertRaisesRegex(ApiError, "Disconnected"):
            camera.take(0)

    def test_capture_preserves_30fps_evidence_while_preview_is_throttled(self):
        emitted = []
        camera = Camera(emitted.append)
        image = np.zeros((100, 100, 3), np.uint8)
        reads = 0

        def read():
            nonlocal reads
            reads += 1
            if reads == 8:
                camera.stopped.set()
            return True, image

        with patch("backend.viso.native.cv2.VideoCapture") as factory, \
                patch("backend.viso.native.monotonic", side_effect=[100 + index / 30 for index in range(8)]):
            device = factory.return_value
            device.isOpened.return_value = True
            device.read.side_effect = read
            camera.start(0)
            camera.thread.join(timeout=2)
            self.assertFalse(camera.thread.is_alive())
            self.assertEqual(len(camera.frames), 6)
            timestamps = [stamp for stamp, _ in camera.frames]
            self.assertAlmostEqual(timestamps[-1] - timestamps[-2], 1 / 30)
            self.assertLess(len(emitted), reads)
            device.release.assert_called_once()


class NativePipeTests(unittest.TestCase):
    def test_real_worker_protocol_errors_inference_and_eof_cleanup(self):
        root = Path(__file__).resolve().parents[2]
        commands = [
            {"id": 1, "command": "status"},
            ["malformed"],
            {"id": 2, "command": "unsupported"},
            {"id": 3, "command": "analyze", "data": {"image": "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", np.zeros((100, 100, 3), np.uint8))[1]).decode()}},
            {"id": 4, "command": "cancel"},
        ]
        worker = subprocess.run([sys.executable, "-m", "backend.viso.native", "--ephemeral"], cwd=root,
                                input="\n".join(json.dumps(command) for command in commands) + "\n",
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(worker.returncode, 0, worker.stderr)
        messages = [json.loads(line) for line in worker.stdout.splitlines()]
        self.assertEqual(messages[0], {"event": "ready"})
        self.assertTrue(messages[1]["result"]["engine"]["ready"])
        self.assertIn("error", messages[2])
        self.assertIn("error", messages[3])
        self.assertEqual(messages[4]["result"]["face_count"], 0)
        self.assertEqual(messages[5]["result"]["state"], "locked")


if __name__ == "__main__":
    unittest.main()
