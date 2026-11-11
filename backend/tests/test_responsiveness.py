import unittest
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend.tests.test_liveness import observation
from backend.viso.enrollment import Enrollment, pose_matches
from backend.viso.native import Camera, NativeHost
from backend.viso.recognition import decode_image, InputError
from backend.viso.service import SandboxService
from backend.viso.storage import ProfileStore


class ResponsivenessTests(unittest.TestCase):
    def test_slow_camera_cannot_count_the_same_frame_as_multiple_enrollment_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True))
            camera = Camera(lambda _: None)
            camera.latest = (100.01, np.zeros((100, 100, 3), np.uint8))
            host = NativeHost(service, camera)
            with patch("backend.viso.native.monotonic", return_value=100.1), patch("backend.viso.service.monotonic", return_value=100):
                host.handle("enrollment.start", {"name": "Person"})
                with patch.object(service, "observe", return_value=observation()) as observe:
                    for _ in range(6):
                        host.handle("enrollment.tick", {})
                    observe.assert_called_once()
            self.assertFalse(service.enrollment.embeddings)

    def test_native_camera_keeps_raw_frames_and_signin_never_encodes_preview(self):
        camera = Camera(lambda _: None, preview=False)
        image = np.zeros((100, 100, 3), np.uint8)
        reads = 0
        blocked, finish = threading.Event(), threading.Event()
        def read():
            nonlocal reads
            reads += 1
            if reads > 1:
                blocked.set()
                finish.wait(2)
                camera.stopped.set()
            return True, image
        with patch("backend.viso.native.cv2.VideoCapture") as factory, patch("backend.viso.native.cv2.imencode") as encode:
            factory.return_value.isOpened.return_value = True
            factory.return_value.read.side_effect = read
            camera.start(0)
            self.assertTrue(blocked.wait(1))
            self.assertIs(decode_image(camera.frame()), image)
            self.assertFalse(image.flags.writeable)
            finish.set()
            camera.thread.join(2)
            encode.assert_not_called()
            camera.stop()
            self.assertIsNone(camera.latest)
            self.assertFalse(camera.frames)

    def test_native_frame_validation_rejects_wrong_types_shapes_and_sizes(self):
        for image in (np.zeros((100, 100)), np.zeros((100, 100, 4), np.uint8), np.zeros((40, 40, 3), np.uint8), np.zeros((100, 100, 3), np.float32)):
            with self.assertRaises(InputError):
                decode_image(image)

    def test_circle_sectors_allow_small_motion_but_require_the_correct_direction(self):
        for step, yaw, pitch in (("left", 10, 2), ("right", -10, -2), ("up", 2, -7), ("down", -2, 7), ("up_left", 10, -7), ("down_right", -10, 7)):
            self.assertTrue(pose_matches(step, yaw, pitch, 16))
            self.assertFalse(pose_matches(step, 0, 0, 0))
            self.assertFalse(pose_matches(step, yaw, pitch, 25))

    def test_three_distinct_observations_with_gentle_motion_capture_after_short_pause(self):
        enrollment = Enrollment("test", "Person", 100)
        for now, yaw in ((100.01, 0), (100.13, 3), (100.26, 7)):
            enrollment.observe(observation(yaw=yaw), now)
        self.assertEqual(len(enrollment.embeddings), 1)
        self.assertEqual(enrollment.baseline[0], 3)
        # Neutral faces still cannot fill the directional template.
        for now in (100.4, 100.6, 100.8):
            enrollment.observe(observation(yaw=3), now)
        self.assertEqual(len(enrollment.embeddings), 1)


if __name__ == "__main__":
    unittest.main()
