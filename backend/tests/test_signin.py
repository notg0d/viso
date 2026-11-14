import copy
import json
import unittest
from unittest.mock import Mock, patch

from backend.viso.recognition import MODEL_ID
from backend.viso.signin import main, validate_profile, verify


def profile():
    vector = [1.] + [0.] * 127
    return {"id": "test-profile", "model_id": MODEL_ID, "source": "camera", "guided": True,
            "samples": 5, "embedding": vector, "templates": [vector[:] for _ in range(5)]}


class SignInTests(unittest.TestCase):
    def test_prewarm_finishes_before_readiness_or_profile_and_never_opens_camera(self):
        events = []
        engine = Mock()
        engine.warmup.side_effect = lambda: events.append("warmup")
        def request(*args):
            events.append("profile")
            return json.dumps({"command": "validate", "profile": profile()}) + "\n"
        with patch("backend.viso.signin.sys.argv", ["signin.py", "--prewarm"]), \
                patch("backend.viso.signin.sys.stdin") as stdin, \
                patch("backend.viso.signin.sys.stdout"), \
                patch("backend.viso.signin.FaceEngine", return_value=engine), \
                patch("backend.viso.signin.Camera") as camera, \
                patch("backend.viso.signin.ProfileStore") as store, \
                patch("builtins.print", side_effect=lambda line, **kwargs: events.append(json.loads(line))):
            stdin.readline.side_effect = request
            main()
        self.assertEqual(events, ["warmup", {"event": "ready"}, "profile", {"event": "validated"}])
        camera.assert_not_called()
        store.assert_not_called()
        engine.close.assert_called_once_with()

    def test_only_current_completed_normalized_camera_profiles(self):
        valid = profile()
        self.assertIs(validate_profile(valid), valid)
        for key, value in (("model_id", "old"), ("source", "image"), ("guided", False),
                           ("samples", 1), ("embedding", [1]), ("templates", []), ("id", "")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile(dict(valid, **{key: value}))
        for number in (float("nan"), float("inf"), 0., 2.):
            invalid = copy.deepcopy(valid)
            invalid["templates"][0][0] = number
            with self.subTest(number=number), self.assertRaises(ValueError):
                validate_profile(invalid)

    def test_blink_prompt_ack_precedes_more_evidence_and_final_release(self):
        events, calls = [], []
        results = iter([
            {"attempt": {"state": "scanning", "message": "Look ahead"}},
            {"attempt": {"state": "scanning", "message": "Blink now"}, "prompt_pending": True},
            {"attempt": {"state": "scanning", "message": "Open eyes"}},
            {"attempt": {"state": "unlocked", "message": "Accepted"}},
        ])
        host = Mock(signin_camera=2)
        host.signin_exposure_assist = True
        host.camera.diagnostics.return_value = {"exposure": "off"}
        def handle(command, data):
            calls.append((command, data))
            return next(results) if command == "attempt.tick" else {}
        host.handle.side_effect = handle
        def ack():
            self.assertEqual(events[-1]["event"], "prompt")
            self.assertEqual(calls[-1][0], "attempt.tick")
            return True
        verify(host, events.append, ack)
        self.assertEqual(calls[0], ("camera.start", {"index": 2, "exposure_assist": True}))
        self.assertEqual(calls[1], ("attempt.start", {"threshold": .55}))
        self.assertEqual([call[0] for call in calls][4], "attempt.ack")
        self.assertEqual(events[-1], {"event": "accepted"})
        self.assertEqual(calls[-1][0], "camera.stop")

    def test_lighting_guidance_keeps_blink_prompt_and_rollback_status(self):
        host = Mock(signin_camera=0, signin_exposure_assist=True)
        host.camera.diagnostics.return_value = {"exposure": "limited"}
        lighting = {"state": "low", "scope": "face", "brightness": 30, "message": "Low light: add a light in front of you."}
        def handle(command, data):
            if command == "attempt.tick":
                return {"attempt": {"state": "scanning", "message": "Blink now"}, "prompt_pending": True, "observation": {"lighting": lighting}}
            return {}
        host.handle.side_effect = handle
        events = []
        with self.assertRaises(ValueError):
            verify(host, events.append, lambda: False)
        self.assertEqual(events[0]["event"], "prompt")
        self.assertTrue(events[0]["message"].startswith("Blink now "))
        self.assertIn("Low light", events[0]["message"])
        self.assertIn("unavailable", events[0]["message"])
        self.assertNotIn("accepted", str(events))

    def test_cancel_or_expiry_never_releases_credential(self):
        for state in ("expired", "locked", "rejected", "scanning"):
            host = Mock(signin_camera=0)
            host.handle.return_value = {"attempt": {"state": state, "message": "Denied"}, "prompt_pending": True}
            events = []
            with self.subTest(state=state), self.assertRaises(ValueError):
                verify(host, events.append, lambda: False)
            self.assertNotIn({"event": "accepted"}, events)
            self.assertNotIn("attempt.ack", [call.args[0] for call in host.handle.call_args_list])


if __name__ == "__main__":
    unittest.main()
