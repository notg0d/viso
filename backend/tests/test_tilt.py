"""Tilt regressions use controlled geometry/observations, not webcam accuracy claims."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from backend.tests.test_liveness import observation
from backend.tests.test_sandbox import profile
from backend.viso.attention import Attention, AttentionEngine, EyeCalibration, apply_eye_state, eye_geometry, eye_state
from backend.viso.enrollment import Enrollment
from backend.viso.service import SandboxService
from backend.viso.sessions import Attempt
from backend.viso.storage import ProfileStore


def eyes(pitch=-5, left=.26, right=.27, left_ear=.22, right_ear=.22, raw=.20, yaw=0, roll=0):
    return Attention(eye_state(left, right, left_ear, right_ear), left, right, left_ear, right_ear,
                     yaw, pitch, roll, left_raw_ear=raw, right_raw_ear=raw)


def tilted_eye(pitch, ear, origin=(240, 180, 0)):
    c, s = np.cos(np.deg2rad(pitch)), np.sin(np.deg2rad(pitch))
    rotation = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    local = np.array([[-20, 0, 0], [-10, 20 * ear, 0], [10, 20 * ear, 0],
                      [20, 0, 0], [10, -20 * ear, 0], [-10, -20 * ear, 0]])
    return (local @ rotation.T) * [1, -1, -1] + origin, rotation


class TiltGeometryTests(unittest.TestCase):
    def test_open_aperture_is_recovered_through_upward_rotation(self):
        for pitch in (0, -15, -25, -35):
            points, rotation = tilted_eye(pitch, .19)
            raw, corrected = eye_geometry(points, rotation, list(range(6)), (640, 360))
            self.assertAlmostEqual(raw, .19 * np.cos(np.deg2rad(pitch)))
            self.assertAlmostEqual(corrected, .19)
            self.assertEqual(eye_state(.1, .1, corrected, corrected), "open")

    def test_closed_apertures_stay_closed_and_correction_is_bounded(self):
        for pitch in (-35, -55, -75):
            points, rotation = tilted_eye(pitch, .08)
            raw, corrected = eye_geometry(points, rotation, list(range(6)), (640, 360))
            self.assertLessEqual(corrected, raw * 1.25)
            self.assertEqual(eye_state(.8, .8, corrected, corrected), "closed")
        points, rotation = tilted_eye(0, 0)
        points[1:3, 2] = 40  # Depth separation by itself is not eyelid aperture.
        self.assertEqual(eye_geometry(points, rotation, list(range(6)), (640, 360)), (0, 0))

    def test_tiny_offscreen_and_invalid_eyes_are_unknown(self):
        points, rotation = tilted_eye(-20, .2)
        for broken in (points * .1, points - [300, 0, 0], points * float("nan")):
            self.assertTrue(np.isnan(eye_geometry(broken, rotation, list(range(6)), (640, 360))).all())

    def test_engine_uses_width_scaled_depth_and_rejects_invalid_rotations(self):
        # A non-square image exposes accidental height scaling of normalized Z.
        width, height = 640, 360
        points = np.tile([320., 180., 0.], (478, 1))
        for ids, origin in (([362, 385, 387, 263, 373, 380], (360, 160, 0)),
                            ([33, 160, 158, 133, 153, 144], (280, 160, 0))):
            eye, rotation = tilted_eye(-30, .19, origin)
            points[ids] = eye
        matrix = np.eye(4)
        matrix[:3, :3] = rotation
        result = SimpleNamespace(
            face_landmarks=[[SimpleNamespace(x=x / width, y=y / height, z=z / width) for x, y, z in points]],
            face_blendshapes=[[SimpleNamespace(category_name=name, score=.1) for name in ("eyeBlinkLeft", "eyeBlinkRight")]],
            facial_transformation_matrixes=[matrix])
        engine = AttentionEngine.__new__(AttentionEngine)
        engine.landmarker = SimpleNamespace(detect=lambda _: result)
        face = np.array([200, 80, 240, 240, 0, 0, 0, 0, 320, 180])
        image = np.zeros((height, width, 3), dtype=np.uint8)
        measured = engine.observe(image, face)
        self.assertEqual(measured.eyes, "open")
        self.assertAlmostEqual(measured.left_ear, .19)
        self.assertLess(measured.left_raw_ear, .18)
        for invalid in (np.zeros((4, 4)), np.full((4, 4), np.nan), np.ones((4, 4)), np.eye(2), np.diag([-1., 1, 1, 1])):
            result.facial_transformation_matrixes = [invalid]
            self.assertEqual(engine.observe(image, face).eyes, "unknown")


class TiltCalibrationTests(unittest.TestCase):
    def calibration(self, pitch=-5):
        calibration = EyeCalibration()
        for _ in range(3):
            calibration.classify(eyes(pitch=pitch), calibrating=True)
        return calibration

    def test_bounded_chin_up_bias_can_keep_both_eyes_open(self):
        calibration = self.calibration()
        frame = eyes(pitch=-18, left=.39, right=.40, left_ear=.205, right_ear=.205, raw=.18)
        self.assertEqual(frame.eyes, "uncertain")
        self.assertEqual(calibration.classify(frame), "open")
        self.assertEqual(EyeCalibration().classify(frame), "uncertain")

    def test_winks_squints_raw_floor_pose_limits_and_missing_tracking_do_not_relax(self):
        calibration = self.calibration()
        base = eyes(pitch=-18, left=.39, right=.40, left_ear=.205, right_ear=.205, raw=.18)
        for changes in ({"left_blink": .7}, {"right_blink": .7}, {"left_ear": .15}, {"right_ear": .15},
                        {"left_blink": .46}, {"left_raw_ear": .13}, {"right_raw_ear": float("nan")},
                        {"pitch": 0}, {"pitch": -36}, {"yaw": 26}, {"roll": 21},
                        {"pitch": None}, {"eyes": "unknown"}, {"eyes": "closed"}):
            with self.subTest(changes=changes):
                self.assertNotEqual(calibration.classify(replace(base, **changes)), "open")

    def test_inferred_open_cannot_train_or_drift_the_baseline(self):
        calibration = self.calibration()
        original = list(calibration.samples)
        for _ in range(20):
            frame = eyes(pitch=-18, left=.39, right=.40)
            apply_eye_state(frame, calibration.classify(frame, calibrating=True))
            self.assertEqual(frame.eye_method, "pose-calibrated")
            calibration.classify(frame, calibrating=True)
        self.assertEqual(calibration.samples, original)
        self.assertNotEqual(calibration.classify(eyes(pitch=-18, left=.50, right=.50)), "open")

    def test_relative_blinks_compare_only_similar_poses(self):
        frame = eyes(pitch=-22, left=.48, right=.49, left_ear=.12, right_ear=.12, raw=.10)
        self.assertEqual(self.calibration(pitch=-16).classify(frame), "closed")
        self.assertEqual(self.calibration(pitch=0).classify(frame), "uncertain")


class TiltFlowTests(unittest.TestCase):
    def prompt(self, attempt, pitch=-5):
        for now in (100.1, 100.2, 100.3):
            attempt.observe(.8, now=now, attention=eyes(pitch=pitch))
        self.assertEqual(attempt.phase, "blink")

    def test_tilted_open_blink_reopen_unlocks_only_after_confirmation(self):
        attempt = Attempt("test", "user", "camera", .55, 100)
        self.prompt(attempt)
        up = eyes(pitch=-18, left=.39, right=.40)
        self.assertEqual(attempt.observe(.8, now=100.4, attention=up)["phase"], "blink")
        self.assertEqual(up.eyes, "open")
        attempt.observe(.8, now=100.5, attention=eyes(pitch=-18, left=.8, right=.8, left_ear=.10, right_ear=.10, raw=.09))
        self.assertEqual(attempt.phase, "reopen")
        attempt.observe(.8, now=100.6, attention=eyes(pitch=-18, left=.39, right=.40))
        self.assertEqual(attempt.phase, "confirm")
        self.assertEqual(attempt.observe(.8, now=100.75, attention=eyes(pitch=-18, left=.39, right=.40))["state"], "unlocked")

    def test_short_relative_blink_at_upward_pose(self):
        attempt = Attempt("test", "user", "camera", .55, 100)
        self.prompt(attempt, pitch=-18)
        frame = eyes(pitch=-20, left=.48, right=.49, left_ear=.12, right_ear=.12, raw=.10)
        self.assertEqual(attempt.observe(.8, now=100.35, attention=frame)["phase"], "reopen")
        self.assertEqual(frame.eye_method, "relative-blink")

    def test_tilt_alone_never_satisfies_blink_even_with_absolute_closed_prediction(self):
        for coefficient in (.48, .8):
            attempt = Attempt("test", "user", "camera", .55, 100)
            self.prompt(attempt)
            for now in (100.4, 100.5, 100.6):
                attempt.observe(.8, now=now, attention=eyes(pitch=-25, left=coefficient, right=coefficient, left_ear=.12, right_ear=.12))
                self.assertEqual(attempt.phase, "blink")
            for now in (100.7, 100.8, 100.9):
                attempt.observe(.8, now=now, attention=eyes(pitch=-18, left=.39, right=.40))
                self.assertNotEqual(attempt.state, "unlocked")

    def test_either_eye_closing_at_tilt_blocks_final_confirmation(self):
        for side in ("left", "right"):
            attempt = Attempt("test", "user", "camera", .55, 100)
            self.prompt(attempt, pitch=-18)
            attempt.observe(.8, now=100.4, attention=eyes(pitch=-18, left=.8, right=.8, left_ear=.1, right_ear=.1))
            attempt.observe(.8, now=100.5, attention=eyes(pitch=-18))
            frame = eyes(pitch=-18, **{side: .8, side + "_ear": .1})
            self.assertEqual(attempt.observe(.8, now=100.7, attention=frame)["phase"], "identity")
            self.assertNotEqual(attempt.state, "unlocked")

    def test_lost_identity_or_gap_discards_tilt_calibration(self):
        for score, now in ((.2, 100.4), (None, 100.4), (.8, 102)):
            attempt = Attempt("test", "user", "camera", .55, 100)
            self.prompt(attempt)
            attempt.observe(score, now=now, attention=eyes(pitch=-18, left=.39, right=.40))
            self.assertEqual(attempt.calibration.samples, [])
            self.assertEqual(attempt.phase, "identity")

    def test_enrollment_captures_upward_pose_with_bounded_bias(self):
        enrollment = Enrollment("test", "Name", 100)
        poses = ((0, -5), (16, -5), (0, -5), (-16, -5), (0, -5), (0, -17), (0, -5), (0, 7))
        for index, (yaw, pitch) in enumerate(poses):
            for offset in (0, .2, .4):
                frame = observation(yaw=yaw, pitch=pitch)
                frame.attention = eyes(yaw=yaw, pitch=pitch, left=.39 if index == 5 else .26, right=.40 if index == 5 else .27)
                result = enrollment.observe(frame, 100.1 + index * .6 + offset)
            if index == 5:
                self.assertEqual(result["captured"], 4)
                self.assertEqual(frame.attention.eye_method, "pose-calibrated")
        self.assertEqual(result["state"], "ready")

    def test_enrollment_resets_references_on_missing_changed_face_or_gap(self):
        for bad, now in ((observation(other=True), 100.4), (observation(eyes="unknown"), 100.4), (observation(), 102)):
            enrollment = Enrollment("test", "Name", 100)
            for tick in (100.1, 100.2, 100.3):
                frame = observation()
                frame.attention = eyes()
                enrollment.observe(frame, tick)
            self.assertEqual(len(enrollment.calibration.samples), 3)
            enrollment.observe(bad, now)
            self.assertEqual(enrollment.calibration.samples, [])

    def test_cached_identity_cannot_train_tilt_references(self):
        attempt = Attempt("test", "user", "camera", .55, 100)
        self.prompt(attempt)
        original = list(attempt.calibration.samples)
        attempt.observe(.8, now=100.4, attention=eyes(pitch=-18, left=.1, right=.1), identity_checked=False)
        self.assertEqual(attempt.calibration.samples, original)

    def test_enrollment_never_captures_a_wink_or_bilateral_closed_eyes_at_tilt(self):
        for left, right in ((.8, .27), (.26, .8), (.8, .8)):
            enrollment = Enrollment("test", "Name", 100)
            poses = ((0, -5), (16, -5), (0, -5), (-16, -5), (0, -5))
            for index, (yaw, pitch) in enumerate(poses):
                for offset in (0, .2, .4):
                    frame = observation()
                    frame.attention = eyes(yaw=yaw, pitch=pitch)
                    enrollment.observe(frame, 100.1 + index * .6 + offset)
            self.assertEqual(enrollment.public()["captured"], 3)
            for now in (103.1, 103.3, 103.5):
                frame = observation()
                frame.attention = eyes(pitch=-17, left=left, right=right,
                                       left_ear=.1 if left == .8 else .22, right_ear=.1 if right == .8 else .22)
                result = enrollment.observe(frame, now)
                self.assertEqual(result["captured"], 3)
                self.assertEqual(result["hold_progress"], 0)

    def test_enrollment_api_reports_calibrated_open_state(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True))
            service.enrollment = Enrollment("test", "Name", 100)
            for index, now in enumerate((100.1, 100.2, 100.3, 100.4)):
                frame = observation()
                frame.attention = eyes(pitch=-18 if index == 3 else -5, left=.39 if index == 3 else .26, right=.40 if index == 3 else .27)
                with patch.object(service, "observe", return_value=frame), patch("backend.viso.service.monotonic", return_value=now), patch("backend.viso.enrollment.monotonic", return_value=now):
                    result = service.dispatch("POST", "/api/enrollments/test/frame", {})
            self.assertEqual(result["observation"]["attention"]["eyes"], "open")
            self.assertEqual(result["observation"]["attention"]["eye_method"], "pose-calibrated")

    def test_service_returns_effective_eye_state_after_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True))
            service.store.save(profile())
            attempt = Attempt("test", service.store.profile["id"], "camera", .55, 100)
            service.attempts[attempt.id] = attempt
            self.prompt(attempt)
            frame = observation()
            frame.attention = eyes(pitch=-18, left=.39, right=.40)
            with patch.object(service, "observe", return_value=frame), patch("backend.viso.sessions.monotonic", return_value=100.4):
                result = service.dispatch("POST", "/api/attempts/test/frame", {})
            self.assertEqual(result["observation"]["attention"]["eyes"], "open")
            self.assertEqual(result["observation"]["attention"]["eye_method"], "pose-calibrated")
            self.assertEqual(result["attempt"]["phase"], "blink")


if __name__ == "__main__":
    unittest.main()
