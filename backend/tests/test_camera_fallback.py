"""Synthetic drivers only: fallback, ownership and diagnostic privacy gates."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from backend.tests.test_sandbox import profile
from backend.viso.native import Camera, NativeHost
from backend.viso.service import ApiError, SandboxService
from backend.viso.storage import ProfileStore


class Device:
    def __init__(self, opened=True, initial=None):
        self.opened = opened
        self.initial = list(initial if initial is not None else [(True, np.zeros((100, 120, 3), np.uint8))])
        self.blocked = threading.Event()
        self.unblock = threading.Event()
        self.released = False
        self.reads = 0
        self.set = Mock()

    def isOpened(self):
        return self.opened

    def read(self):
        self.reads += 1
        if self.initial:
            result = self.initial.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        self.blocked.set()
        if not self.unblock.wait(2):
            raise RuntimeError("Synthetic test driver timed out.")
        return False, None

    def release(self):
        self.released = True


class CameraFallbackTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.camera = Camera(self.events.append, preview=False)
        self.devices = []
        self.calls = []
        self.factory = patch("backend.viso.native.cv2.VideoCapture", side_effect=self.open)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.addCleanup(self.cleanup)

    def open(self, *arguments):
        # Every prior capture must already be released before another opens.
        for previous in self.devices[:len(self.calls)]:
            if isinstance(previous, Device):
                self.assertTrue(previous.released)
        device = self.devices[len(self.calls)]
        self.calls.append(arguments)
        if isinstance(device, Exception):
            raise device
        return device

    def cleanup(self):
        for device in self.devices:
            if isinstance(device, Device):
                device.unblock.set()
        try:
            self.camera.stop()
        except ApiError:
            pass  # Release-failure cases deliberately retire the Camera.

    def test_preferred_open_preserves_parameters_raw_immutable_frames_and_no_preview(self):
        device = Device()
        self.devices = [device]
        result = self.camera.start(0)
        self.assertEqual(result["backend"], "DirectShow")
        self.assertTrue(device.blocked.wait(1))
        self.assertEqual(self.calls, [(0, cv2.CAP_DSHOW, [cv2.CAP_PROP_FRAME_WIDTH, 960, cv2.CAP_PROP_FRAME_HEIGHT, 720])])
        device.set.assert_not_called()
        frame = self.camera.frame()
        self.assertEqual(frame.shape, (100, 120, 3))
        self.assertFalse(frame.flags.writeable)
        self.assertFalse(self.events)

    def test_rejected_open_parameters_fall_back_to_directshow_defaults(self):
        self.devices = [RuntimeError(r"C:\Users\Private\driver"), Device()]
        self.camera.start(2)
        self.assertEqual(self.calls[1], (2, cv2.CAP_DSHOW))
        self.assertEqual([item["outcome"] for item in self.camera.diagnostics()["attempts"]], ["driver_error", "opened"])
        self.assertNotIn("Private", json.dumps(self.camera.diagnostics()))

    def test_media_foundation_is_last_serial_fallback_and_requires_a_frame(self):
        self.devices = [Device(opened=False), Device(initial=[(False, None)] * 3), Device()]
        result = self.camera.start(0)
        self.assertEqual(result["backend"], "Media Foundation")
        self.assertEqual(self.calls[-1], (0, cv2.CAP_MSMF))
        self.assertEqual([item["outcome"] for item in self.camera.diagnostics()["attempts"]], ["not_opened", "no_frame", "opened"])
        self.assertEqual(self.devices[1].reads, 3)
        self.assertFalse(self.events)

    def test_initial_empty_reads_can_warm_up_but_do_not_enter_evidence_queue(self):
        self.devices = [Device(initial=[(False, None), (True, np.empty((0, 0, 3), np.uint8)),
                                        (True, np.zeros((100, 120, 3), np.uint8))])]
        self.camera.start(0)
        self.assertTrue(self.devices[0].blocked.wait(1))
        self.assertEqual(len(self.camera.frames), 1)
        self.assertEqual(self.devices[0].reads, 4)  # Fourth read waits, after valid startup.

    def test_invalid_frames_do_not_count_as_open_or_leak_into_queue(self):
        self.devices = [Device(initial=[(True, np.zeros((100, 100), np.uint8))] * 3),
                        Device(initial=[(True, np.zeros((100, 100, 3), np.float32))] * 3), Device(opened=False)]
        with self.assertRaisesRegex(ApiError, "desktop-app camera permissions"):
            self.camera.start(0)
        self.assertEqual(len(self.calls), 3)
        self.assertIsNone(self.camera.latest)
        self.assertFalse(self.camera.frames)
        self.assertTrue(all(device.released for device in self.devices))
        self.assertEqual(len(self.events), 1)

    def test_valid_frame_after_shared_startup_deadline_is_not_published_or_retried(self):
        clock = [100.]
        device = Device()
        original = device.read

        def read():
            clock[0] = 113.
            return original()

        device.read = read
        self.devices = [device]
        with patch("backend.viso.native.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(ApiError, "too long"):
                self.camera.start(0)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(device.released)
        self.assertIsNone(self.camera.latest)
        self.assertFalse(self.camera.frames)
        self.assertEqual(self.camera.diagnostics()["attempts"][0]["outcome"], "timeout")

    def test_shared_deadline_is_not_reset_for_later_candidates(self):
        clock = [100.]
        self.devices = [Device(opened=False), Device(opened=False), Device()]
        original = self.open

        def open(*arguments):
            device = original(*arguments)
            clock[0] += 5
            return device

        with patch("backend.viso.native.cv2.VideoCapture", side_effect=open), \
                patch("backend.viso.native.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(ApiError, "too long"):
                self.camera.start(0)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(self.devices[-1].released)
        self.assertIsNone(self.camera.latest)

    def test_blocked_constructor_times_out_without_concurrent_reopen_or_late_frame(self):
        entered, unblock = threading.Event(), threading.Event()
        device = Device()
        self.devices = [device]
        self.camera.START_TIMEOUT = .03
        self.camera.STOP_TIMEOUT = .01

        def open(*arguments):
            entered.set()
            unblock.wait(2)
            return self.open(*arguments)

        try:
            with patch("backend.viso.native.cv2.VideoCapture", side_effect=open):
                with self.assertRaisesRegex(ApiError, "did not stop"):
                    self.camera.start(0)
                self.assertTrue(entered.is_set())
                with self.assertRaisesRegex(ApiError, "did not stop"):
                    self.camera.start(0)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.camera.diagnostics()["failure"], "startup_timeout")
                unblock.set()
                self.camera.thread.join(1)
                self.assertFalse(self.camera.thread.is_alive())
        finally:
            unblock.set()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(device.released)
        self.assertIsNone(self.camera.latest)
        self.assertFalse(self.events)

    def test_cancel_during_first_read_never_publishes_or_falls_back(self):
        device = Device(initial=[])
        self.devices = [device]
        result = []

        def start():
            try:
                result.append(self.camera.start(0))
            except ApiError as error:
                result.append(error.message)

        starter = threading.Thread(target=start)
        starter.start()
        try:
            self.assertTrue(device.blocked.wait(1))
            original_join = self.camera.thread.join

            def join(timeout):
                device.unblock.set()
                original_join(timeout)

            with patch.object(self.camera.thread, "join", side_effect=join):
                self.camera.stop()
            starter.join(1)
            self.assertFalse(starter.is_alive())
            self.assertEqual(result, ["Camera startup canceled."])
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(device.released)
            self.assertIsNone(self.camera.latest)
            self.assertFalse(self.events)
        finally:
            device.unblock.set()
            starter.join(2)

    def test_release_failure_retires_camera_and_prevents_fallback_and_restart(self):
        device = Device(opened=False)
        device.release = Mock(side_effect=RuntimeError("sensitive driver exception"))
        self.devices = [device]
        with self.assertRaisesRegex(ApiError, "did not release"):
            self.camera.start(0)
        with self.assertRaisesRegex(ApiError, "did not release"):
            self.camera.start(0)
        self.assertEqual(len(self.calls), 1)
        self.assertIs(self.camera.unreleased_device, device)
        self.assertEqual(self.camera.diagnostics()["failure"], "release_failed")
        self.assertNotIn("sensitive", json.dumps(self.events) + json.dumps(self.camera.diagnostics()))

    def test_stream_failure_clears_evidence_and_does_not_auto_reopen(self):
        device = Device()
        self.devices = [device]
        self.camera.start(0)
        self.assertTrue(device.blocked.wait(1))
        device.unblock.set()
        self.camera.thread.join(1)
        self.assertFalse(self.camera.thread.is_alive())
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(device.released)
        self.assertIsNone(self.camera.latest)
        self.assertFalse(self.camera.frames)
        self.assertEqual(self.camera.diagnostics()["failure"], "capture_failed")
        with self.assertRaisesRegex(ApiError, "new test"):
            self.camera.frame()

    def test_diagnostics_cannot_mutate_capture_state_or_expose_images(self):
        self.devices = [Device()]
        self.camera.start(0)
        snapshot = self.camera.diagnostics()
        self.assertEqual((snapshot["width"], snapshot["height"]), (120, 100))
        self.assertIsNotNone(snapshot["frame_age_ms"])
        snapshot["attempts"][0]["outcome"] = "mutated"
        self.assertEqual(self.camera.diagnostics()["attempts"][0]["outcome"], "opened")
        self.assertNotIn("image", json.dumps(snapshot))
        self.assertEqual(len(self.camera.frames), 1)
        self.assertEqual(len(self.calls), 1)

    def test_diagnostics_measures_capture_cadence_not_nominal_driver_fps(self):
        self.camera.sample_times.extend(100 + index / 30 for index in range(30))
        self.assertEqual(self.camera.diagnostics()["capture_hz"], 30.)
        self.assertEqual(self.calls, [])

    def test_invalid_index_does_not_open_any_device(self):
        for index in (True, -1, 33, "0", .5, None):
            with self.subTest(index=index), self.assertRaises(ApiError):
                self.camera.start(index)
        self.assertEqual(self.calls, [])


class DiagnosticPrivacyTests(unittest.TestCase):
    def test_private_diagnostics_are_allowlisted_read_only_and_profile_free(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory), ephemeral=True)
            store.save(profile())
            store.error = "secret-account / secret-path / secret-password"
            service = SandboxService(None, store, "secret-model-path")
            service.token = "secret-token"
            camera = Camera(lambda event: None)
            host = NativeHost(service, camera)
            with patch("backend.viso.native.cv2.VideoCapture") as capture, patch.object(service, "dispatch") as dispatch:
                result = host.handle("diagnostics", {})
                capture.assert_not_called()
                dispatch.assert_not_called()
            self.assertEqual(set(result), {"schema", "runtime", "engine", "storage", "storage_error", "camera"})
            self.assertEqual(result["schema"], 1)
            self.assertTrue(result["storage_error"])
            self.assertFalse(result["camera"]["running"])
            encoded = json.dumps(result, allow_nan=False)
            for private in ("secret", directory, "embedding", "templates", "profile", "password", "token"):
                self.assertNotIn(private, encoded)

    def test_missing_optional_distribution_metadata_does_not_break_diagnostics(self):
        from importlib.metadata import PackageNotFoundError
        with tempfile.TemporaryDirectory() as directory:
            host = NativeHost(SandboxService(None, ProfileStore(Path(directory), ephemeral=True)), Camera(lambda event: None))
            with patch("backend.viso.native.version", side_effect=PackageNotFoundError):
                self.assertIsNone(host.handle("diagnostics", {})["runtime"]["mediapipe"])
