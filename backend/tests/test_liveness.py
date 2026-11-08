import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend.viso.attention import Attention, EyeCalibration, eye_state, head_angles
from backend.viso.enrollment import Enrollment, pose_matches
from backend.viso.recognition import Observation
from backend.viso.service import ApiError, SandboxService
from backend.viso.sessions import Attempt
from backend.viso.storage import ProfileStore
from backend.tests.test_sandbox import profile


def observation(eyes="open", yaw=0, pitch=0, roll=0, other=False):
    vector = np.array(([0, 1] if other else [1, 0]) + [0] * 126, dtype=np.float32)
    return Observation(1, "Face ready", vector, attention=Attention(eyes=eyes, yaw=yaw, pitch=pitch, roll=roll))


class BlinkTests(unittest.TestCase):
    def make(self):
        return Attempt("test", "user", "camera", .55, 100)

    def prompt(self, attempt):
        for time in (100.1, 100.2, 100.3):
            attempt.observe(.8, "open", time)
        self.assertEqual(attempt.phase, "blink")

    def test_complete_blink_unlocks_only_after_stable_reopened_eyes(self):
        attempt = self.make()
        self.prompt(attempt)
        self.assertEqual(attempt.observe(.8, "closed", 100.5)["phase"], "reopen")
        self.assertEqual(attempt.state, "scanning")
        self.assertEqual(attempt.observe(.8, "open", 100.7)["phase"], "confirm")
        self.assertEqual(attempt.state, "scanning")
        self.assertEqual(attempt.observe(.8, "open", 100.85)["state"], "unlocked")

    def test_open_only_closed_only_and_winks_never_unlock(self):
        for eyes in ("open", "closed", "uncertain", "unknown"):
            with self.subTest(eyes=eyes):
                attempt = self.make()
                self.prompt(attempt)
                for tick in range(4, 190):
                    attempt.observe(.8, eyes, 100 + tick / 10)
                    self.assertNotEqual(attempt.state, "unlocked")

    def test_eyes_must_start_open_and_blink_after_prompt(self):
        attempt = self.make()
        attempt.observe(.8, "closed", 100.01)
        self.prompt(attempt)
        attempt.observe(.8, "open", 100.5)
        self.assertEqual(attempt.phase, "blink")
        # A short blink immediately after seeing the prompt is no longer ignored.
        early = self.make()
        self.prompt(early)
        self.assertEqual(early.observe(.8, "closed", 100.35)["phase"], "reopen")
        self.assertEqual(early.observe(.8, "open", 100.40)["phase"], "confirm")
        self.assertEqual(early.observe(.8, "open", 100.55)["state"], "unlocked")

    def test_wrong_missing_or_untrackable_face_clears_blink_evidence(self):
        for score, eyes in ((.2, "open"), (None, "open"), (float("nan"), "open"), (.8, "unknown")):
            with self.subTest(score=score, eyes=eyes):
                attempt = self.make()
                self.prompt(attempt)
                attempt.observe(.8, "closed", 100.5)
                self.assertEqual(attempt.observe(score, eyes, 100.6)["phase"], "identity")
                for time in (100.7, 100.85, 101):
                    self.assertNotEqual(attempt.observe(.8, "open", time)["state"], "unlocked")

    def test_either_eye_closing_during_final_confirmation_resets(self):
        for eyes in ("closed", "uncertain", "unknown"):
            attempt = self.make()
            self.prompt(attempt)
            attempt.observe(.8, "closed", 100.5)
            attempt.observe(.8, "open", 100.7)
            self.assertEqual(attempt.observe(.8, eyes, 100.85)["phase"], "identity")

    def test_stale_evidence_and_clock_reversal_reset(self):
        for time in (100.4, 102):
            attempt = self.make()
            self.prompt(attempt)
            attempt.observe(.8, "closed", 100.5)
            self.assertEqual(attempt.observe(.8, "open", time)["phase"], "identity")

    def test_long_eye_closure_and_challenge_timeout_require_new_blink(self):
        attempt = self.make()
        self.prompt(attempt)
        for time in (100.5, 101, 101.5, 102.1):
            attempt.observe(.8, "closed", time)
        self.assertEqual(attempt.phase, "identity")
        attempt = self.make()
        self.prompt(attempt)
        for tick in range(4, 65):
            attempt.observe(.8, "open", 100 + tick / 10)
        self.assertEqual(attempt.phase, "identity")

    def test_expired_attempt_and_image_source_cannot_unlock(self):
        attempt = self.make()
        self.prompt(attempt)
        self.assertEqual(attempt.observe(.8, "closed", 121)["state"], "expired")
        self.assertEqual(attempt.observe(.8, "open", 121.3)["state"], "expired")
        image = Attempt("image", "user", "image", .55, 100)
        self.assertEqual(image.observe(.8, "open", 100.1)["state"], "blocked")


class AttentionTests(unittest.TestCase):
    def test_relative_blink_detects_quick_closure_but_not_winks_or_squints(self):
        calibration = EyeCalibration()
        for _ in range(3):
            calibration.classify(Attention("open", .1, .12, .28, .27), calibrating=True)
        # A short blink's sampled peak need not reach the old .60 coefficient.
        self.assertEqual(calibration.classify(Attention("uncertain", .45, .46, .14, .15)), "closed")
        for frame in (Attention("uncertain", .45, .12, .14, .27),
                      Attention("uncertain", .1, .46, .28, .15),
                      Attention("uncertain", .2, .2, .20, .20),
                      Attention("unknown", .9, .9, .1, .1)):
            self.assertNotEqual(calibration.classify(frame), "closed")
        self.assertEqual(calibration.classify(Attention("uncertain", .1, .1, .16, .16)), "uncertain")

    def test_both_eyes_must_agree_and_geometry_must_confirm(self):
        self.assertEqual(eye_state(.1, .1, .28, .27), "open")
        self.assertEqual(eye_state(.9, .85, .09, .1), "closed")
        for values in ((.1, .9, .28, .1), (.9, .1, .1, .28), (.5, .5, .2, .2), (.1, .1, .1, .1), (.9, .9, .3, .3)):
            self.assertEqual(eye_state(*values), "uncertain")
        for value in (float("nan"), float("inf"), -1):
            self.assertEqual(eye_state(value, .1, .2, .2), "unknown")

    def test_pose_rotation_signs_and_direction_windows(self):
        angle = np.deg2rad(20)
        c, s = np.cos(angle), np.sin(angle)
        yaw, pitch, _ = head_angles(np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]))
        self.assertAlmostEqual(yaw, 20)
        self.assertTrue(pose_matches("left", yaw, pitch, 0))
        self.assertFalse(pose_matches("right", yaw, pitch, 0))
        yaw, pitch, _ = head_angles(np.array([[1, 0, 0], [0, c, -s], [0, s, c]]))
        self.assertAlmostEqual(pitch, 20)
        self.assertFalse(pose_matches("down", yaw, pitch, 0))  # use a smaller, easier pitch target
        self.assertTrue(pose_matches("down", 0, 12, 0))
        self.assertFalse(pose_matches("up", yaw, pitch, 0))
        for pose in ((40, 0, 0), (18, 25, 0), (18, 0, 30), (float("nan"), 0, 0)):
            self.assertFalse(pose_matches("left", *pose))


class GuidedEnrollmentTests(unittest.TestCase):
    def hold(self, enrollment, frame, start):
        for offset in (0, .2, .5):
            result = enrollment.observe(frame, start + offset)
        return result

    def test_five_distinct_stable_angles_complete_enrollment(self):
        enrollment = Enrollment("test", "Name", 100)
        for index, (yaw, pitch) in enumerate(((0, 5), (18, 5), (-18, 5), (0, -10), (0, 20))):
            if enrollment.returning:
                self.hold(enrollment, observation(pitch=5), 100 + index * 2)
            result = self.hold(enrollment, observation(yaw=yaw, pitch=pitch), 101 + index * 2)
            self.assertEqual(result["captured"], index + 1)
        self.assertEqual(result["state"], "ready")
        self.assertNotIn("embeddings", result)

    def test_same_frontal_photo_does_not_fill_directional_samples(self):
        enrollment = Enrollment("test", "Name", 100)
        self.hold(enrollment, observation(), 101)
        for start in range(102, 110):
            self.hold(enrollment, observation(), start)
        self.assertEqual(len(enrollment.embeddings), 1)
        self.assertEqual(enrollment.public()["step"], "left")

    def test_neutral_calibration_uses_the_hold_and_guidance_is_relative(self):
        enrollment = Enrollment("test", "Name", 100)
        for now, yaw, pitch in ((101, 2, -6), (101.2, 3, -5), (101.4, 5, -3)):
            enrollment.observe(observation(yaw=yaw, pitch=pitch), now)
        self.assertEqual(enrollment.baseline, (3, -5))
        for now in (101.6, 101.7, 101.8):
            result = enrollment.observe(observation(yaw=19, pitch=-5), now)
        self.assertEqual(result["guidance"]["yaw"], 16)
        self.assertEqual(result["guidance"]["pitch"], 0)
        self.assertEqual(result["guidance"]["target_yaw"], 14)

    def test_each_turn_requires_recentering_and_cannot_skip_to_opposite_side(self):
        enrollment = Enrollment("test", "Name", 100)
        self.hold(enrollment, observation(), 101)
        self.hold(enrollment, observation(yaw=16), 102)
        self.assertTrue(enrollment.returning)
        result = self.hold(enrollment, observation(yaw=-16), 103)
        self.assertEqual(result["captured"], 2)
        self.assertEqual(result["title"], "Return to the center")
        self.hold(enrollment, observation(), 104)
        self.assertFalse(enrollment.returning)
        self.assertEqual(self.hold(enrollment, observation(yaw=-16), 105)["captured"], 3)

    def test_wrong_pose_closed_eyes_changed_person_and_missing_face_reset_hold(self):
        for frame in (observation(yaw=-18), observation(eyes="closed", yaw=18), observation(other=True, yaw=18), Observation(0, "No face")):
            enrollment = Enrollment("test", "Name", 100)
            self.hold(enrollment, observation(), 101)
            enrollment.observe(observation(yaw=18), 102)
            enrollment.observe(frame, 102.3)
            self.assertEqual(enrollment.observe(observation(yaw=18), 102.5)["captured"], 1)
            self.assertEqual(enrollment.hold_progress, 0)

    def test_unstable_head_and_stale_frames_do_not_satisfy_hold(self):
        enrollment = Enrollment("test", "Name", 100)
        enrollment.observe(observation(yaw=-8), 101)
        enrollment.observe(observation(yaw=8), 101.2)
        enrollment.observe(observation(yaw=-8), 101.5)
        self.assertEqual(len(enrollment.embeddings), 0)
        enrollment.observe(observation(yaw=-8), 104)
        self.assertEqual(enrollment.hold_progress, 0)

    def test_expired_enrollment_discards_samples(self):
        enrollment = Enrollment("test", "Name", 100)
        self.hold(enrollment, observation(), 101)
        result = enrollment.observe(observation(yaw=18), 191)
        self.assertEqual(result["state"], "expired")
        self.assertEqual(enrollment.embeddings, [])

    def test_api_requires_completed_sequence_and_cancellation_revokes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True))
            with self.assertRaises(ApiError):
                service.dispatch("POST", "/api/enroll", {"name": "Test", "source": "camera", "images": ["fake"] * 5})
            started = service.dispatch("POST", "/api/enrollments", {"name": "Test"})
            endpoint = f"/api/enrollments/{started['id']}"
            with self.assertRaises(ApiError):
                service.dispatch("POST", endpoint + "/finish")
            service.dispatch("DELETE", endpoint)
            with self.assertRaises(ApiError):
                service.dispatch("POST", endpoint + "/frame", {"image": "fake"})
            self.assertIsNone(service.store.profile)

    def test_service_uses_measured_pose_and_only_saves_after_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True))
            with patch("backend.viso.service.monotonic", return_value=100):
                started = service.dispatch("POST", "/api/enrollments", {"name": "Test"})
            endpoint = f"/api/enrollments/{started['id']}"
            poses = ((0, 0), (18, 0), (0, 0), (-18, 0), (0, 0), (0, -12), (0, 0), (0, 12))
            for index, (yaw, pitch) in enumerate(poses):
                for offset in (0, .2, .5):
                    now = 101 + index + offset
                    with patch.object(service, "observe", return_value=observation(yaw=yaw, pitch=pitch)), patch("backend.viso.service.monotonic", return_value=now), patch("backend.viso.enrollment.monotonic", return_value=now):
                        result = service.dispatch("POST", endpoint + "/frame", {"eyes": "closed", "yaw": 90})
            self.assertEqual(result["enrollment"]["state"], "ready")
            self.assertIsNone(service.store.profile)
            with patch("backend.viso.service.monotonic", return_value=110):
                status = service.dispatch("POST", endpoint + "/finish")
            self.assertTrue(status["profile"]["guided"])
            self.assertEqual(status["profile"]["samples"], 5)
            self.assertNotIn("embedding", status["profile"])

    def test_service_cannot_accept_client_claimed_eye_state(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.save(profile())
            service = SandboxService(None, store)
            started = service.dispatch("POST", "/api/attempts", {"source": "camera"})
            endpoint = f"/api/attempts/{started['id']}/frame"
            with patch.object(service, "observe", return_value=observation(eyes="closed")):
                for _ in range(5):
                    result = service.dispatch("POST", endpoint, {"eyes": "open", "blink_verified": True})
                    self.assertEqual(result["attempt"]["phase"], "identity")
                    self.assertNotEqual(result["attempt"]["state"], "unlocked")


if __name__ == "__main__":
    unittest.main()
