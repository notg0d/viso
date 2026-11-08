import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend.tests.test_liveness import observation
from backend.tests.test_sandbox import profile
from backend.viso.attention import Attention
from backend.viso.recognition import DEFAULT_THRESHOLD, normalized, profile_similarity, similarity
from backend.viso.service import SandboxService
from backend.viso.sessions import Attempt
from backend.viso.storage import ProfileStore, dpapi


def box(x=.2):
    return [x, .2, .4, .5]


class MotionTests(unittest.TestCase):
    def make(self):
        attempt = Attempt("test", "user", "camera", .55, 100)
        for now in (100.1, 100.2, 100.3):
            attempt.observe(.8, "open", now, box=box())
        self.assertEqual(attempt.phase, "blink")
        return attempt

    def test_brief_borderline_motion_preserves_prompt_then_requires_a_real_blink(self):
        attempt = self.make()
        paused = attempt.observe(.52, "open", 100.35, box=box(.22))
        self.assertTrue(paused["recovering"])
        self.assertEqual(paused["phase"], "blink")
        self.assertEqual(attempt.last_identity_at, 100.3)
        self.assertFalse(attempt.can_track_open_eyes(Attention(eyes="open"), box(.22), 100.36))
        attempt.observe(.8, "open", 100.4, box=box(.23))
        self.assertEqual(attempt.challenge, 1)
        self.assertFalse(attempt.recovering)
        self.assertEqual(attempt.state, "scanning")
        attempt.observe(.8, "closed", 100.45, box=box(.24))
        attempt.observe(.8, "open", 100.5, box=box(.25))
        self.assertEqual(attempt.observe(.8, "open", 100.65, box=box(.26))["state"], "unlocked")

    def test_repeated_weak_frames_cannot_extend_recovery_or_unlock(self):
        attempt = self.make()
        for now in (100.35, 100.42, 100.49):
            result = attempt.observe(.52, "open", now, box=box(.22))
            self.assertTrue(result["recovering"])
            self.assertEqual(result["state"], "scanning")
        self.assertEqual(attempt.observe(.52, "open", 100.51, box=box(.22))["phase"], "identity")
        self.assertFalse(attempt.recovering)
        self.assertIsNone(attempt.last_identity_score)

    def test_late_strong_recovery_also_discards_the_old_challenge(self):
        attempt = self.make()
        attempt.observe(.52, "open", 100.35, box=box(.22))
        result = attempt.observe(.8, "open", 100.55, box=box(.22))
        self.assertEqual(result["phase"], "identity")
        self.assertEqual(result["streak"], 1)
        for now in (100.65, 100.75):
            attempt.observe(.8, "open", now, box=box(.22))
        self.assertEqual(attempt.challenge, 2)
        self.assertIsNone(attempt.closed_at)

    def test_clear_mismatch_missing_eyes_and_large_jumps_reset_immediately(self):
        for score, eyes, current_box in ((.2, "open", box()), (.48, "open", box()),
                                         (None, "open", box()), (float("nan"), "open", box()),
                                         (.52, "closed", box()), (.52, "uncertain", box()),
                                         (.52, "unknown", box()), (.52, "open", box(.5)),
                                         (.52, "open", None)):
            with self.subTest(score=score, eyes=eyes, box=current_box):
                attempt = self.make()
                result = attempt.observe(score, eyes, 100.35, box=current_box)
                self.assertEqual(result["phase"], "identity")
                self.assertFalse(result["recovering"])

    def test_final_confirmation_restarts_after_motion_and_needs_latest_strong_open_frame(self):
        attempt = self.make()
        attempt.observe(.8, "closed", 100.35, box=box())
        attempt.observe(.8, "open", 100.4, box=box())
        self.assertEqual(attempt.observe(.52, "open", 100.5, box=box(.22))["state"], "scanning")
        self.assertIsNone(attempt.reopened_at)
        for now in (100.56, 100.67):
            self.assertEqual(attempt.observe(.8, "open", now, box=box(.23))["state"], "scanning")
        self.assertEqual(attempt.observe(.8, "open", 100.69, box=box(.24), latest=False)["state"], "scanning")
        self.assertEqual(attempt.observe(.8, "open", 100.70, box=box(.24))["state"], "unlocked")

    def test_eye_closure_or_lost_eyes_during_recovery_revokes_completed_blink(self):
        for eyes in ("closed", "uncertain", "unknown"):
            attempt = self.make()
            attempt.observe(.8, "closed", 100.35, box=box())
            attempt.observe(.8, "open", 100.4, box=box())
            attempt.observe(.52, "open", 100.45, box=box(.22))
            self.assertEqual(attempt.observe(.8, eyes, 100.5, box=box(.22))["phase"], "identity")
            self.assertIsNone(attempt.closed_at)

    def test_near_open_measurement_jitter_pauses_but_cannot_complete_confirmation(self):
        attempt = self.make()
        attempt.observe(.8, "closed", 100.35, box=box())
        attempt.observe(.8, "open", 100.4, box=box())
        jitter = Attention("uncertain", .31, .26, .24, .23)
        result = attempt.observe(.8, now=100.45, box=box(.22), attention=jitter)
        self.assertTrue(result["recovering"])
        self.assertEqual(result["state"], "scanning")
        self.assertEqual(result["phase"], "confirm")
        self.assertIsNone(attempt.reopened_at)
        self.assertEqual(attempt.last_identity_at, 100.4)
        self.assertEqual(attempt.observe(.8, "open", 100.5, box=box(.22))["state"], "scanning")
        self.assertEqual(attempt.observe(.8, "open", 100.65, box=box(.23))["state"], "unlocked")

    def test_uncertain_eye_recovery_is_bounded_and_rejects_winks_and_weak_identity(self):
        jitter = Attention("uncertain", .31, .26, .24, .23)
        for score, eyes in ((.52, jitter), (.8, Attention("uncertain", .7, .1, .1, .25)),
                             (.8, Attention("uncertain", .1, .7, .25, .1)),
                             (.8, Attention("uncertain", .31, .26, .17, .23)),
                             (.8, Attention("unknown", .31, .26, .24, .23))):
            with self.subTest(score=score, eyes=eyes):
                attempt = self.make()
                attempt.observe(.8, "closed", 100.35, box=box())
                attempt.observe(.8, "open", 100.4, box=box())
                self.assertEqual(attempt.observe(score, now=100.45, box=box(), attention=eyes)["phase"], "identity")
        attempt = self.make()
        for now in (100.35, 100.42, 100.49):
            self.assertTrue(attempt.observe(.8, now=now, box=box(), attention=jitter)["recovering"])
        self.assertEqual(attempt.observe(.8, now=100.51, box=box(), attention=jitter)["phase"], "identity")
        self.assertEqual(attempt.state, "scanning")

    def test_fast_tracking_follows_small_steps_without_extending_identity_age_or_anchor(self):
        attempt = self.make()
        eyes = Attention(eyes="open")
        for now, x in ((100.35, .22), (100.4, .24), (100.45, .26)):
            self.assertTrue(attempt.can_track_open_eyes(eyes, box(x), now))
            attempt.observe(.8, "open", now, box=box(x), identity_checked=False)
        self.assertEqual(attempt.last_identity_at, 100.3)
        self.assertEqual(attempt.last_identity_box, box())
        self.assertFalse(attempt.can_track_open_eyes(eyes, box(.29), 100.48))
        self.assertFalse(attempt.can_track_open_eyes(eyes, box(.26), 100.51))
        self.assertFalse(attempt.can_track_open_eyes(Attention(eyes="closed"), box(.26), 100.46))

    def test_buffered_weak_last_frame_cannot_use_cached_score_to_unlock(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.save(profile())
            service = SandboxService(None, store)
            attempt = self.make()
            attempt.profile_id = store.profile["id"]
            service.attempts[attempt.id] = attempt
            frames = []
            measured = []
            for offset, eyes, score in ((350, "closed", .8), (400, "open", .8), (550, "open", .52)):
                frame = observation(eyes)
                frame.embedding = np.array([score, np.sqrt(1 - score ** 2)] + [0] * 126, dtype=np.float32)
                frame.box = box()
                measured.append(frame)
                frames.append({"image": "fixture", "offset_ms": offset})
            with patch.object(service, "observe", side_effect=measured), patch("backend.viso.service.monotonic", return_value=100.6):
                result = service.dispatch("POST", "/api/attempts/test/frames", {"frames": frames})
            self.assertAlmostEqual(result["observation"]["similarity"], .52)
            self.assertTrue(result["attempt"]["recovering"])
            self.assertEqual(result["attempt"]["state"], "scanning")


def direction(degrees):
    angle = np.deg2rad(degrees)
    return np.array([np.cos(angle), np.sin(angle)] + [0] * 126, dtype=np.float32)


class MultiViewTests(unittest.TestCase):
    def views(self):
        templates = [direction(angle) for angle in (-28, -24, -20, 22, 28)]
        return {**profile(), "samples": 5, "templates": [view.tolist() for view in templates],
                "embedding": normalized(np.mean(templates, axis=0)).tolist()}

    def test_two_consistent_views_can_match_an_angle_the_centroid_misses(self):
        enrolled = self.views()
        probe = direction(75)
        self.assertLess(similarity(probe, enrolled["embedding"]), DEFAULT_THRESHOLD)
        self.assertGreater(profile_similarity(probe, enrolled), DEFAULT_THRESHOLD)

    def test_one_strong_view_alone_cannot_override_a_failed_centroid(self):
        enrolled = self.views()
        probe = direction(83)
        self.assertGreater(max(similarity(probe, view) for view in enrolled["templates"]), DEFAULT_THRESHOLD)
        self.assertLess(profile_similarity(probe, enrolled), DEFAULT_THRESHOLD)

    def test_legacy_profiles_keep_their_original_score(self):
        enrolled = profile()
        probe = direction(35)
        self.assertEqual(profile_similarity(probe, enrolled), similarity(probe, enrolled["embedding"]))

    def test_service_saves_views_without_exposing_vectors_in_status(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            service = SandboxService(None, store)
            result = service.save_profile("Fixture", [direction(-20), direction(0), direction(20)], "image")
            self.assertEqual(len(store.profile["templates"]), 3)
            self.assertEqual(result["profile"]["matching"], "multi-view")
            self.assertNotIn("templates", json.dumps(result))
            self.assertNotIn("embedding", json.dumps(result))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_encrypted_views_roundtrip_and_malformed_views_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder))
            store.save(self.views())
            self.assertNotIn(b"templates", store.path.read_bytes())
            restored = ProfileStore(Path(folder))
            self.assertIsNone(restored.error)
            self.assertEqual(restored.public()["matching"], "multi-view")
            self.assertAlmostEqual(profile_similarity(direction(75), restored.profile),
                                   profile_similarity(direction(75), store.profile))
            for templates in ([[1, 0]], [[1] * 128] * 6, [[float("nan")] * 128] * 5):
                invalid = {**self.views(), "templates": templates}
                store.path.write_bytes(dpapi(json.dumps(invalid).encode()))
                broken = ProfileStore(Path(folder))
                self.assertIsNone(broken.profile)
                self.assertIsNotNone(broken.error)


if __name__ == "__main__":
    unittest.main()
