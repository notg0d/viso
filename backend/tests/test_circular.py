import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from backend.tests.test_liveness import observation
from backend.tests.test_motion import direction
from backend.tests.test_signin import profile as legacy_profile
from backend.viso.enrollment import Enrollment, STEPS, TARGETS, ENROLLMENT_VERSION, pose_matches
from backend.viso.recognition import InputError, ProfileMatcher, normalized
from backend.viso.service import SandboxService
from backend.viso.signin import validate_profile
from backend.viso.storage import ProfileStore, dpapi


def circular_profile():
    result = legacy_profile()
    result.update(samples=len(STEPS), templates=[result["embedding"][:] for _ in STEPS],
                  template_groups=[step[0] for step in STEPS], enrollment_version=ENROLLMENT_VERSION,
                  observations=3 * len(STEPS),
                  poses=[{"step": step[0], "yaw": TARGETS[step[0]][0], "pitch": TARGETS[step[0]][1], "observations": 3} for step in STEPS])
    return result


class CircularTests(unittest.TestCase):
    def test_two_passes_and_mandatory_interpass_recenter(self):
        enrollment = Enrollment("test", "Person", 100)
        now = 100.1
        for index, step in enumerate(STEPS):
            if index == 9:
                self.assertTrue(enrollment.returning)
                for offset in (0, .13, .26):
                    result = enrollment.observe(observation(yaw=14), now + offset)
                self.assertEqual(result["captured"], 9)
                now += .4
                for offset in (0, .13):
                    enrollment.observe(observation(), now + offset)
                self.assertFalse(enrollment.returning)
                now += .3
            yaw, pitch = TARGETS[step[0]][:2]
            for offset in (0, .12, .25):
                result = enrollment.observe(observation(yaw=yaw, pitch=pitch), now + offset)
            self.assertEqual(result["captured"], index + 1)
            now += .4
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["circuit"], 2)
        self.assertEqual(result["circuit_captured"], 8)
        self.assertEqual(result["observations"], 51)
        self.assertEqual(len(enrollment.hold_samples), 0)

    def test_diagonals_cannot_be_filled_with_cardinal_or_neutral_poses(self):
        for step in ("up_left", "up_right", "down_left", "down_right"):
            for yaw, pitch in ((0, 0), (14, 0), (-14, 0), (0, 10), (0, -10)):
                self.assertFalse(pose_matches(step, yaw, pitch, 0))

    def test_duplicate_timestamp_cannot_supply_more_views(self):
        enrollment = Enrollment("test", "Person", 100)
        for _ in range(20):
            enrollment.observe(observation(), 100.1)
        self.assertEqual(enrollment.embeddings, [])
        self.assertLessEqual(len(enrollment.hold_samples), 1)

    def test_new_format_strict_validation_and_legacy_compatibility(self):
        good = circular_profile()
        self.assertIs(validate_profile(good), good)
        self.assertIsNotNone(validate_profile(legacy_profile()))
        for key, value in (("samples", 16), ("samples", True), ("observations", 50),
                           ("enrollment_version", "unknown"), ("template_groups", ["left"] * 17),
                           ("poses", []), ("templates", good["templates"][:5])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile(dict(good, **{key: value}))
        for key, value in (("observations", 1), ("yaw", float("nan")), ("pitch", True), ("step", "right")):
            invalid = copy.deepcopy(good)
            invalid["poses"][0][key] = value
            with self.assertRaises(ValueError):
                validate_profile(invalid)

    def test_repeated_same_pose_cannot_supply_two_matching_votes(self):
        probe = direction(90)
        profile = {"embedding": direction(0), "templates": [direction(0), probe, probe],
                   "template_groups": ["center", "left", "left"]}
        self.assertLess(ProfileMatcher(profile).score(probe), .55)
        profile["template_groups"][-1] = "up_left"
        self.assertGreater(ProfileMatcher(profile).score(probe), .99)

    def test_interleaved_circuits_match_explicit_distinct_group_reduction(self):
        rng = np.random.default_rng(42)
        profile = circular_profile()
        views = np.asarray([normalized(rng.normal(size=128)) for _ in STEPS])
        profile["templates"] = views.tolist()
        profile["embedding"] = normalized(rng.normal(size=128)).tolist()
        matcher = ProfileMatcher(profile)
        for _ in range(50):
            probe = normalized(rng.normal(size=128))
            scores = views @ probe
            groups = profile["template_groups"]
            independent = sorted(max(scores[index] for index, name in enumerate(groups) if name == group)
                                 for group in set(groups))
            expected = max(float(np.dot(probe, profile["embedding"])), independent[-2])
            self.assertAlmostEqual(matcher.score(probe), expected, places=6)

    def test_finite_components_with_overflowing_norm_are_rejected(self):
        with np.errstate(over="ignore", invalid="ignore"), self.assertRaises(InputError):
            normalized(np.full(128, np.finfo(np.float32).max, dtype=np.float32))

    def test_compiled_matcher_is_reused_and_profile_delete_releases_it(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.profile = circular_profile()
            service = SandboxService(None, store)
            with patch("backend.viso.service.ProfileMatcher", wraps=ProfileMatcher) as factory:
                for _ in range(100):
                    self.assertGreater(service.score(observation()), .99)
                factory.assert_called_once()
            self.assertEqual(service._matcher.views.dtype, np.float32)
            self.assertTrue(service._matcher.views.flags.c_contiguous)
            service.dispatch("DELETE", "/api/profile")
            self.assertIsNone(service._matcher)
            self.assertIsNone(service._matched_profile)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_encrypted_circular_profile_roundtrip_and_partial_coverage_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder))
            store.save(circular_profile())
            restored = ProfileStore(Path(folder))
            self.assertIsNone(restored.error)
            self.assertEqual(restored.public()["samples"], 17)
            self.assertNotIn("templates", restored.public())
            self.assertIsNotNone(validate_profile(restored.profile))
            invalid = circular_profile()
            invalid["template_groups"][3] = "left"
            store.path.write_bytes(dpapi(json.dumps(invalid).encode()))
            self.assertIsNotNone(ProfileStore(Path(folder)).error)

    def test_close_releases_all_model_handles_and_is_idempotent(self):
        from backend.viso.recognition import FaceEngine
        from unittest.mock import Mock
        engine = FaceEngine.__new__(FaceEngine)
        attention = engine.attention = Mock()
        engine.detector = engine.recognizer = object()
        engine.close(); engine.close()
        attention.close.assert_called_once()
        self.assertIsNone(engine.recognizer)
        self.assertIsNone(engine.detector)
