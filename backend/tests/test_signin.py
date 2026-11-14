import copy
import json
import threading
import unittest
from unittest.mock import Mock, patch

from backend.viso.recognition import MODEL_ID
from backend.viso.signin import main, validate_profile, verify


def profile():
    vector = [1.] + [0.] * 127
    return {"id": "test-profile", "model_id": MODEL_ID, "source": "camera", "guided": True,
            "samples": 5, "embedding": vector, "templates": [vector[:] for _ in range(5)]}


class SignInTests(unittest.TestCase):
    def test_prewarm_finishes_before_readiness_and_validation_and_never_opens_camera(self):
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
        self.assertLess(events.index("warmup"), events.index({"event": "ready"}))
        self.assertLess(events.index({"event": "ready"}), events.index({"event": "validated"}))
        self.assertLess(events.index("profile"), events.index({"event": "validated"}))
        camera.assert_not_called()
        store.assert_not_called()
        engine.close.assert_called_once_with()

    def test_idle_prewarm_reports_ready_while_waiting_for_a_request_with_camera_off(self):
        ready = threading.Event()
        engine = Mock()
        def request(*args):
            self.assertTrue(ready.wait(2), "Model readiness was blocked by stdin.")
            camera.assert_not_called()
            return json.dumps({"command": "validate", "profile": profile()}) + "\n"
        def printed(line, **kwargs):
            if json.loads(line)["event"] == "ready":
                ready.set()
        with patch("backend.viso.signin.sys.argv", ["signin.py", "--prewarm"]), \
                patch("backend.viso.signin.sys.stdin") as stdin, \
                patch("backend.viso.signin.sys.stdout"), \
                patch("backend.viso.signin.FaceEngine", return_value=engine), \
                patch("backend.viso.signin.Camera") as camera, \
                patch("builtins.print", side_effect=printed):
            stdin.readline.side_effect = request
            main()
        engine.warmup.assert_called_once_with()
        engine.close.assert_called_once_with()

    def test_selected_camera_starts_during_model_warmup_without_early_evidence(self):
        events = []
        warming, opening = threading.Event(), threading.Event()
        engine, camera = Mock(), Mock()
        camera_start = {"running": True, "lighting": {"state": "low"}, "exposure": "tuned"}
        def warmup():
            events.append("warmup.started")
            warming.set()
            self.assertTrue(opening.wait(2), "Camera startup waited for model warmup.")
            events.append("warmup.finished")
        def start(index, assist):
            self.assertTrue(warming.wait(2))
            self.assertEqual((index, assist), (2, True))
            events.append("camera.started")
            opening.set()
            return camera_start
        def scan(host, emit, acknowledge, start=None):
            self.assertEqual(start, camera_start)
            self.assertIn("warmup.finished", events)
            events.append("scan")
        engine.warmup.side_effect = warmup
        camera.start.side_effect = start
        with patch("backend.viso.signin.sys.argv", ["signin.py", "--prewarm"]), \
                patch("backend.viso.signin.sys.stdin") as stdin, \
                patch("backend.viso.signin.sys.stdout"), \
                patch("backend.viso.signin.FaceEngine", return_value=engine), \
                patch("backend.viso.signin.Camera", return_value=camera) as make_camera, \
                patch("backend.viso.signin.ProfileStore") as store, \
                patch("backend.viso.signin.NativeHost") as host, \
                patch("backend.viso.signin.verify", side_effect=scan), \
                patch("builtins.print", side_effect=lambda line, **kwargs: events.append(json.loads(line))):
            stdin.readline.return_value = json.dumps({"command": "verify", "profile": profile(), "camera": 2, "exposure_assist": True}) + "\n"
            main()
        self.assertLess(events.index("camera.started"), events.index("warmup.finished"))
        self.assertLess(events.index({"event": "ready"}), events.index("scan"))
        self.assertEqual([event for event in events if isinstance(event, dict)][0], {"event": "ready"})
        self.assertNotIn({"event": "accepted"}, events)
        make_camera.assert_called_once()
        store.assert_called_once()
        host.return_value.cancel.assert_called_once_with()
        camera.stop.assert_called_once_with()
        engine.close.assert_called_once_with()

    def test_invalid_prewarm_request_never_opens_camera_and_closes_models(self):
        for request in ({"command": "verify", "profile": {}},
                        {"command": "other", "profile": profile()}):
            engine = Mock()
            with self.subTest(request=request), \
                    patch("backend.viso.signin.sys.argv", ["signin.py", "--prewarm"]), \
                    patch("backend.viso.signin.sys.stdin") as stdin, \
                    patch("backend.viso.signin.sys.stdout"), \
                    patch("backend.viso.signin.FaceEngine", return_value=engine), \
                    patch("backend.viso.signin.Camera") as camera, \
                    patch("backend.viso.signin.verify") as scan, \
                    patch("builtins.print"), self.assertRaises(SystemExit):
                stdin.readline.return_value = json.dumps(request) + "\n"
                main()
            camera.assert_not_called()
            scan.assert_not_called()
            engine.close.assert_called_once_with()

    def test_overlapped_startup_failure_closes_camera_and_models_without_a_scan(self):
        for failure in ("models", "camera"):
            opening = threading.Event()
            engine, camera = Mock(), Mock()
            def warmup():
                self.assertTrue(opening.wait(2))
                if failure == "models":
                    raise RuntimeError("Synthetic model failure")
            def start(*args):
                opening.set()
                if failure == "camera":
                    raise ValueError("Synthetic camera failure")
                return {"running": True}
            engine.warmup.side_effect = warmup
            camera.start.side_effect = start
            events = []
            with self.subTest(failure=failure), \
                    patch("backend.viso.signin.sys.argv", ["signin.py", "--prewarm"]), \
                    patch("backend.viso.signin.sys.stdin") as stdin, \
                    patch("backend.viso.signin.sys.stdout"), \
                    patch("backend.viso.signin.FaceEngine", return_value=engine), \
                    patch("backend.viso.signin.Camera", return_value=camera), \
                    patch("backend.viso.signin.NativeHost") as host, \
                    patch("backend.viso.signin.verify") as scan, \
                    patch("builtins.print", side_effect=lambda line, **kwargs: events.append(json.loads(line))), \
                    self.assertRaises(SystemExit):
                stdin.readline.return_value = json.dumps({"command": "verify", "profile": profile()}) + "\n"
                main()
            host.assert_not_called()
            scan.assert_not_called()
            self.assertTrue(any(event["event"] == "error" for event in events))
            self.assertFalse(any(event["event"] in ("accepted", "prompt") for event in events))
            self.assertTrue(camera.stop.called)
            engine.close.assert_called_once_with()

    def test_ready_camera_is_not_reopened_and_still_requires_a_new_attempt(self):
        host = Mock()
        host.handle.return_value = {"attempt": {"state": "rejected", "message": "Denied"}}
        events = []
        with self.assertRaises(ValueError):
            verify(host, events.append, lambda: True, start={"running": True, "exposure": "tuned"})
        self.assertEqual(host.handle.call_args_list[0].args, ("attempt.start", {"threshold": .55}))
        self.assertNotIn("camera.start", [call.args[0] for call in host.handle.call_args_list])
        self.assertFalse(any(event["event"] == "accepted" for event in events))

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
