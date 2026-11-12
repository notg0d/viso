import json
import threading
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from backend.viso.lighting import ExposureTuner, measure_lighting
from backend.viso.native import Camera
from backend.viso.recognition import FaceEngine
from backend.viso.service import ApiError


class Driver:
    def __init__(self, exposure=-8, auto=1):
        self.values = {cv2.CAP_PROP_EXPOSURE: exposure, cv2.CAP_PROP_AUTO_EXPOSURE: auto}
        self.calls = []

    def get(self, prop):
        return self.values[prop]

    def set(self, prop, value):
        self.calls.append((prop, value))
        self.values[prop] = value
        return True


class LightingTests(unittest.TestCase):
    def test_measured_states_and_scope_do_not_change_pixels(self):
        for brightness, expected in ((0, "low"), (54, "low"), (55, "good"), (120, "good"), (211, "bright"), (255, "bright")):
            image = np.full((100, 120, 3), brightness, np.uint8)
            image.setflags(write=False)
            result = measure_lighting(image, "face")
            self.assertEqual(result["state"], expected)
            self.assertEqual(result["scope"], "face")
            self.assertEqual(result["brightness"], brightness)
            self.assertTrue(np.all(image == brightness))
            self.assertEqual(set(result), {"state", "scope", "brightness", "message"})
            json.dumps(result, allow_nan=False)
        image = np.full((100, 100, 3), 180, np.uint8)
        image[:, :50] = 60
        self.assertEqual(measure_lighting(image)["state"], "uneven")

    def test_no_face_still_has_scene_feedback_without_relaxing_recognition(self):
        engine = FaceEngine.__new__(FaceEngine)
        engine.detector = Mock()
        engine.detector.detect.return_value = (None, None)
        result = engine.observe(np.zeros((100, 100, 3), np.uint8))
        self.assertEqual(result.public()["lighting"]["state"], "low")
        self.assertIsNone(result.embedding)
        self.assertEqual(result.face_count, 0)

    def test_aligned_face_light_retains_existing_dark_bright_and_blur_gates(self):
        engine = FaceEngine.__new__(FaceEngine)
        engine.detector = Mock()
        face = np.array([[10, 10, 80, 80] + [40] * 10 + [.99]], np.float32)
        engine.detector.detect.side_effect = lambda _: (None, face.copy())
        engine.recognizer = Mock()
        engine.attention = Mock()
        for brightness in (20, 240, 100):
            engine.recognizer.alignCrop.return_value = np.full((112, 112, 3), brightness, np.uint8)
            result = engine.observe(np.full((100, 100, 3), 120, np.uint8))
            self.assertEqual(result.lighting["scope"], "face")
            self.assertIsNone(result.embedding)
        engine.recognizer.feature.assert_not_called()
        engine.attention.observe.assert_not_called()


class ExposureTests(unittest.TestCase):
    def baseline(self, tuner, hz=30, state="low"):
        for index in range(round(hz * .8) + 2):
            changed = tuner.update(index / hz, {"state": state})
            if tuner.ready or changed:
                return index / hz

    def tune(self, driver=None):
        driver = driver or Driver()
        tuner = ExposureTuner(driver, "DirectShow", True, 0)
        when = self.baseline(tuner)
        self.assertEqual(tuner.state, "settling")
        for index in range(1, 16):
            tuner.update(when + index / 30, {"state": "low"})
        self.assertEqual(tuner.state, "tuned")
        self.assertTrue(tuner.ready)
        return driver, tuner

    def test_off_and_other_backend_never_query_or_write_driver(self):
        for backend, enabled, state in (("DirectShow", False, "off"), ("Media Foundation", True, "unsupported")):
            driver = Mock()
            tuner = ExposureTuner(driver, backend, enabled, 0)
            self.assertTrue(tuner.ready)
            self.assertEqual(tuner.state, state)
            driver.get.assert_not_called()
            driver.set.assert_not_called()

    def test_unsupported_nonfinite_or_ambiguous_driver_properties_never_write(self):
        for exposure, auto in ((0, 0), (float("nan"), 1), (float("inf"), 1), (-14, 1), (-8.5, 1), (-8, .75)):
            driver = Driver(exposure, auto)
            tuner = ExposureTuner(driver, "DirectShow", True, 0)
            self.assertEqual(tuner.state, "unsupported")
            self.assertTrue(tuner.ready)
            self.assertFalse(driver.calls)

    def test_bounded_tuning_settles_and_restores_original_auto_and_exposure(self):
        driver, tuner = self.tune()
        self.assertEqual(driver.values[cv2.CAP_PROP_EXPOSURE], -6)
        self.assertEqual(driver.values[cv2.CAP_PROP_AUTO_EXPOSURE], 0)
        self.assertTrue(tuner.restore())
        self.assertEqual(driver.values, Driver().values)
        self.assertEqual(driver.calls[-1], (cv2.CAP_PROP_AUTO_EXPOSURE, 1))
        self.assertTrue(tuner.restore())
        self.assertEqual(len(driver.calls), 4)

    def test_good_light_slow_baseline_and_long_original_exposure_do_not_tune(self):
        for driver, hz, state, expected in ((Driver(), 30, "good", "not_needed"), (Driver(), 15, "low", "limited"),
                                             (Driver(-6), 30, "low", "limited"), (Driver(-4), 30, "low", "limited")):
            tuner = ExposureTuner(driver, "DirectShow", True, 0)
            self.baseline(tuner, hz, state)
            self.assertEqual(tuner.state, expected)
            self.assertFalse(driver.calls)

    def test_slow_or_overbright_settling_rolls_back_before_first_evidence(self):
        for hz, state in ((15, "low"), (30, "bright")):
            driver = Driver()
            tuner = ExposureTuner(driver, "DirectShow", True, 0)
            when = self.baseline(tuner)
            for index in range(1, round(hz * .5) + 2):
                tuner.update(when + index / hz, {"state": state})
            self.assertTrue(tuner.ready)
            self.assertEqual(tuner.state, "limited")
            self.assertEqual(driver.values, Driver().values)

    def test_live_slowdown_rolls_back_once_and_never_increases_mid_blink(self):
        driver, tuner = self.tune()
        now = tuner.last + .1
        self.assertTrue(tuner.update(now, {"state": "low"}))
        self.assertEqual(tuner.state, "limited")
        self.assertEqual(driver.values, Driver().values)
        for index in range(50):
            tuner.update(now + (index + 1) / 30, {"state": "low"})
        self.assertEqual(len(driver.calls), 4)

    def test_sustained_cadence_below_24hz_rolls_back_even_without_a_long_gap(self):
        driver, tuner = self.tune()
        now = tuner.last
        for index in range(1, 18):
            tuner.update(now + index / 22, {"state": "low"})
        self.assertEqual(tuner.state, "limited")
        self.assertEqual(driver.values, Driver().values)

    def test_failure_false_success_nan_and_exception_restore_without_crashing(self):
        for failure in ("false", "ignored", "nan", "exception"):
            driver = Driver()
            original = driver.set
            def set_value(prop, value):
                if prop == cv2.CAP_PROP_EXPOSURE and value == -6:
                    if failure == "exception":
                        raise RuntimeError("private driver information")
                    if failure == "ignored":
                        return True
                    original(prop, float("nan") if failure == "nan" else value)
                    return failure != "false"
                return original(prop, value)
            driver.set = set_value
            tuner = ExposureTuner(driver, "DirectShow", True, 0)
            self.baseline(tuner)
            self.assertEqual(tuner.state, "unsupported")
            self.assertEqual(driver.values, Driver().values)
            self.assertTrue(tuner.ready)

    def test_failed_restore_is_reported_and_attempts_both_properties(self):
        driver, tuner = self.tune()
        driver.set = Mock(return_value=False)
        self.assertFalse(tuner.restore())
        self.assertEqual(tuner.state, "restore_failed")
        self.assertEqual(driver.set.call_count, 2)

    def test_capture_calibration_is_private_and_restore_precedes_release(self):
        clock = [100.]
        driver = Driver()
        blocked, unblock = threading.Event(), threading.Event()
        reads = [0]
        driver.isOpened = lambda: True
        def read():
            reads[0] += 1
            if reads[0] > 55:
                blocked.set()
                unblock.wait(2)
                return False, None
            clock[0] += 1 / 30
            return True, np.full((100, 120, 3), 30, np.uint8)
        driver.read = read
        driver.release = Mock(side_effect=lambda: self.assertEqual(driver.values, Driver().values))
        camera = Camera(lambda _: None, preview=False)
        try:
            with patch("backend.viso.native.cv2.VideoCapture", return_value=driver), patch("backend.viso.native.monotonic", side_effect=lambda: clock[0]):
                result = camera.start(0, True)
                self.assertEqual(result["exposure"], "tuned")
                self.assertTrue(blocked.wait(1))
                self.assertTrue(all(timestamp >= 101.3 for timestamp, _ in camera.frames))
                self.assertFalse(camera.frame().flags.writeable)
                camera.stopped.set()
                unblock.set()
                camera.stop()
            driver.release.assert_called_once()
        finally:
            unblock.set()
            camera.stop()

    def test_nonboolean_option_is_rejected_before_open(self):
        camera = Camera(lambda _: None)
        for value in (1, "true", None):
            with patch("backend.viso.native.cv2.VideoCapture") as capture, self.assertRaises(ApiError):
                camera.start(0, value)
            capture.assert_not_called()
