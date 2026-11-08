import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.tests.test_liveness import observation
from backend.tests.test_sandbox import profile
from backend.viso.service import ApiError, SandboxService
from backend.viso.storage import ProfileStore


class BufferedCameraTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        store = ProfileStore(Path(self.directory.name), ephemeral=True)
        store.save(profile())
        self.service = SandboxService(None, store)
        with patch("backend.viso.service.monotonic", return_value=100):
            started = self.service.dispatch("POST", "/api/attempts", {"source": "camera"})
        self.endpoint = f"/api/attempts/{started['id']}/frames"
        self.attempt = self.service.attempts[started["id"]]

    def send(self, samples, received):
        frames = [{"offset_ms": offset, "image": str(index)} for index, (offset, _) in enumerate(samples)]
        with patch.object(self.service, "observe", side_effect=[frame for _, frame in samples]), \
                patch("backend.viso.service.monotonic", return_value=received):
            return self.service.dispatch("POST", self.endpoint, {"frames": frames})

    def prompt(self):
        self.send([(100, observation()), (200, observation()), (300, observation())], 100.4)
        self.assertEqual(self.attempt.phase, "blink")

    def test_50ms_blink_survives_batched_delivery_and_only_unlocks_on_latest_open_frame(self):
        self.prompt()
        result = self.send([(400, observation()), (450, observation("closed")),
                            (500, observation()), (650, observation())], 100.7)
        self.assertEqual(result["attempt"]["state"], "unlocked")

    def test_later_closed_or_unknown_eye_frame_prevents_buffered_unlock(self):
        for eyes in ("closed", "uncertain", "unknown"):
            with self.subTest(eyes=eyes):
                self.attempt.reset("reset")
                self.attempt.last_capture_ms = -1
                self.attempt.last_frame_at = None
                self.prompt()
                result = self.send([(400, observation("closed")), (450, observation()),
                                    (600, observation()), (650, observation(eyes))], 100.7)
                self.assertNotEqual(result["attempt"]["state"], "unlocked")

    def test_pre_prompt_frames_cannot_answer_the_challenge(self):
        result = self.send([(100, observation()), (200, observation()), (300, observation()),
                            (350, observation("closed")), (400, observation()), (550, observation())], 100.6)
        self.assertEqual(result["attempt"]["phase"], "blink")
        self.assertIsNone(self.attempt.closed_at)

    def test_changed_identity_during_buffered_blink_discards_evidence(self):
        self.prompt()
        result = self.send([(400, observation("closed", other=True)), (450, observation()),
                            (600, observation())], 100.7)
        self.assertNotEqual(result["attempt"]["state"], "unlocked")

    def test_stale_future_duplicate_and_oversized_batches_are_rejected_before_inference(self):
        for offsets in ([0], [2000], [900, 900], [950, 900], [800] * 7, [True], [float("nan")], []):
            with self.subTest(offsets=offsets), patch.object(self.service, "observe") as observe, \
                    patch("backend.viso.service.monotonic", return_value=101):
                with self.assertRaises(ApiError):
                    self.service.dispatch("POST", self.endpoint, {"frames": [{"offset_ms": x} for x in offsets]})
                observe.assert_not_called()

    def test_long_eye_hold_and_reused_timestamps_do_not_complete_a_blink(self):
        self.prompt()
        self.send([(400, observation("closed")), (700, observation("closed"))], 100.8)
        result = self.send([(1201, observation())], 101.3)
        self.assertEqual(result["attempt"]["phase"], "identity")
        with self.assertRaises(ApiError):
            self.send([(1201, observation())], 101.4)

    def test_fast_eye_lane_refreshes_identity_and_never_skips_blink_evidence(self):
        self.prompt()
        self.attempt.last_identity_at = 100.3
        self.attempt.last_identity_box = [.2, .2, .4, .5]
        self.attempt.last_identity_score = .9
        open_eyes = observation().attention
        self.assertTrue(self.attempt.can_track_open_eyes(open_eyes, [.2, .2, .4, .5], 100.4))
        self.assertFalse(self.attempt.can_track_open_eyes(open_eyes, [.2, .2, .4, .5], 100.51))
        self.assertFalse(self.attempt.can_track_open_eyes(open_eyes, [.5, .2, .4, .5], 100.4))
        for phase in ("identity", "reopen", "confirm"):
            self.attempt.phase = phase
            self.assertFalse(self.attempt.can_track_open_eyes(open_eyes, [.2, .2, .4, .5], 100.4))
        self.attempt.phase = "blink"
        for state in ("closed", "uncertain", "unknown"):
            self.assertFalse(self.attempt.can_track_open_eyes(observation(state).attention, [.2, .2, .4, .5], 100.4))

        checked = []
        states = ["open", "closed", "open", "open"]
        def measure(data, skip_recognition):
            frame = observation(states[int(data["image"])])
            frame.box = [.2, .2, .4, .5]
            frame.identity_checked = not skip_recognition(frame.attention, frame.box)
            if not frame.identity_checked:
                frame.embedding = None
            checked.append(frame.identity_checked)
            return frame
        with patch.object(self.service, "observe", side_effect=measure), patch("backend.viso.service.monotonic", return_value=100.7):
            result = self.service.dispatch("POST", self.endpoint, {"frames": [
                {"offset_ms": offset, "image": str(index)} for index, offset in enumerate((350, 400, 450, 600))]})
        self.assertEqual(checked, [False, True, True, True])
        self.assertEqual(result["attempt"]["state"], "unlocked")
        self.assertTrue(result["observation"]["identity_checked"])


if __name__ == "__main__":
    unittest.main()
