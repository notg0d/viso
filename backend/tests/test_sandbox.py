import base64
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from backend.viso.recognition import DEFAULT_THRESHOLD, MODEL_ID, FaceEngine, InputError, decode_image, normalized, profile_similarity, similarity
from backend.viso.server import ROOT, SandboxServer
from backend.viso.service import ApiError, SandboxService
from backend.viso.storage import ProfileStore

FIXTURES = ROOT / "tests" / ".fixtures"


def encoded(image: np.ndarray) -> str:
    success, data = cv2.imencode(".jpg", image)
    assert success
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def fixture(name: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode((FIXTURES / name).read_bytes()).decode()


def profile():
    return {"id": "test-profile", "name": "Test Identity", "model_id": MODEL_ID, "embedding": [1.0] + [0.0] * 127, "samples": 1, "source": "image", "created_at": "2026-01-01T00:00:00+00:00"}


class ValidationTests(unittest.TestCase):
    def test_invalid_image_inputs(self):
        for value in (None, 123, "data:image/svg+xml;base64,AAAA", "data:image/jpeg;base64,invalid!", "x" * 3_000_001):
            with self.subTest(value=str(value)[:40]), self.assertRaises(InputError):
                decode_image(value)

    def test_invalid_thresholds_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.save(profile())
            service = SandboxService(None, store)
            for threshold in (True, "0.5", -.2, 1.1, float("nan"), float("inf")):
                with self.subTest(threshold=threshold), self.assertRaises(ApiError):
                    service.dispatch("POST", "/api/attempts", {"source": "camera", "threshold": threshold})

    def test_new_attempt_and_profile_deletion_revoke_old_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.save(profile())
            service = SandboxService(None, store)
            first = service.dispatch("POST", "/api/attempts", {"source": "camera"})
            second = service.dispatch("POST", "/api/attempts", {"source": "camera"})
            self.assertNotIn(first["id"], service.attempts)
            self.assertIn(second["id"], service.attempts)
            service.dispatch("DELETE", "/api/profile")
            self.assertEqual(service.attempts, {})
            self.assertIsNone(service.store.profile)


class StorageTests(unittest.TestCase):
    def test_ephemeral_mode_writes_no_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            store.save(profile())
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertNotIn("embedding", store.public())
            self.assertIsNone(ProfileStore(Path(folder), ephemeral=True).profile)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_persists_encrypted_profile_and_deletes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder))
            store.save(profile())
            self.assertNotIn(b"Test Identity", store.path.read_bytes())
            restored = ProfileStore(Path(folder))
            self.assertEqual(restored.profile, store.profile)
            with self.assertRaises(ValueError):
                restored.save(profile())
            restored.clear()
            self.assertFalse(store.path.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_corrupt_profile_is_preserved_until_explicit_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.dpapi"
            path.write_bytes(b"corrupted")
            store = ProfileStore(Path(folder))
            self.assertIsNone(store.profile)
            self.assertIsNotNone(store.error)
            with self.assertRaises(ValueError):
                store.save(profile())
            self.assertEqual(path.read_bytes(), b"corrupted")
            store.clear()
            self.assertIsNone(store.error)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.service = SandboxService(None, ProfileStore(Path(cls.folder.name), ephemeral=True), "Test engine")
        cls.server = SandboxServer(("127.0.0.1", 0), cls.service, Path(cls.folder.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.folder.cleanup()

    def request(self, path, method="GET", data=None, headers=None):
        request = Request(self.url + path, data=data, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_status_is_sandbox_and_contains_no_vectors(self):
        code, body = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(body["mode"], "sandbox")
        self.assertNotIn("embedding", json.dumps(body))

    def test_missing_token_cannot_modify_profile(self):
        self.assertEqual(self.request("/api/profile", "DELETE")[0], 403)

    def test_foreign_origin_and_rebound_host_are_rejected(self):
        for headers in ({"Origin": "https://unrelated.example"}, {"Host": "unrelated.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("/api/status", headers=headers)[0], 403)

    def test_valid_token_can_clear_sandbox(self):
        code, body = self.request("/api/profile", "DELETE", headers={"X-Viso-Token": self.service.token})
        self.assertEqual(code, 200)
        self.assertIsNone(body["profile"])

    def test_oversized_and_malformed_requests_are_rejected(self):
        headers = {"X-Viso-Token": self.service.token, "Content-Type": "application/json"}
        self.assertEqual(self.request("/api/analyze", "POST", b"[]", headers)[0], 400)
        self.assertEqual(self.request("/api/analyze", "POST", b"{}", {**headers, "Content-Length": "16000001"})[0], 413)

    def test_static_traversal_is_rejected(self):
        self.assertEqual(self.request("/%2e%2e/package.json")[0], 404)


class RecognitionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all((FIXTURES / name).exists() for name in ("obama.jpg", "obama2.jpg", "biden.jpg")):
            raise unittest.SkipTest("Run scripts/download_test_fixtures.py for real-model integration tests.")
        cls.engine = FaceEngine(ROOT / "models")
        cls.images = {name: fixture(name) for name in ("obama.jpg", "obama2.jpg", "biden.jpg")}
        cls.observations = {name: cls.engine.observe(decode_image(image)) for name, image in cls.images.items()}

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_different_photos_of_same_person_match(self):
        first, second = self.observations["obama.jpg"], self.observations["obama2.jpg"]
        self.assertIsNotNone(first.embedding, first.message)
        self.assertIsNotNone(second.embedding, second.message)
        self.assertGreater(similarity(first.embedding, second.embedding), DEFAULT_THRESHOLD)

    def test_different_person_does_not_match(self):
        first, second = self.observations["obama.jpg"], self.observations["biden.jpg"]
        self.assertIsNotNone(second.embedding, second.message)
        self.assertLess(similarity(first.embedding, second.embedding), DEFAULT_THRESHOLD)

    def test_blank_warmup_preserves_real_identity_and_eye_measurements(self):
        self.engine.warmup()
        blank = self.engine.observe(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(blank.face_count, 0)
        self.assertIsNone(blank.embedding)
        for name, previous in self.observations.items():
            with self.subTest(name=name):
                current = self.engine.observe(decode_image(self.images[name]))
                self.assertEqual(current.face_count, previous.face_count)
                np.testing.assert_allclose(current.embedding, previous.embedding, rtol=1e-5, atol=1e-6)
                self.assertEqual(current.attention.eyes, previous.attention.eyes)
                self.assertEqual(current.lighting, previous.lighting)

    def test_background_model_preparation_preserves_main_thread_recognition(self):
        from concurrent.futures import ThreadPoolExecutor
        def prepare():
            engine = FaceEngine(ROOT / "models")
            try:
                engine.warmup()
                return engine
            except Exception:
                engine.close()
                raise
        with ThreadPoolExecutor(max_workers=1) as preparation:
            engine = preparation.submit(prepare).result(timeout=30)
        try:
            blank = engine.observe(np.zeros((480, 640, 3), dtype=np.uint8))
            self.assertEqual(blank.face_count, 0)
            self.assertIsNone(blank.embedding)
            for name, previous in self.observations.items():
                with self.subTest(name=name):
                    current = engine.observe(decode_image(self.images[name]))
                    np.testing.assert_allclose(current.embedding, previous.embedding, rtol=1e-5, atol=1e-6)
                    self.assertEqual(current.attention.public(), previous.attention.public())
                    self.assertEqual(current.lighting, previous.lighting)
        finally:
            engine.close()

    def test_moving_portrait_views_match_while_other_identity_stays_below_threshold(self):
        first, second = self.observations["obama.jpg"], self.observations["obama2.jpg"]
        enrolled = {"embedding": normalized(first.embedding + second.embedding).tolist(),
                    "templates": [first.embedding.tolist(), second.embedding.tolist()]}
        for name in ("obama2.jpg", "biden.jpg"):
            image = decode_image(self.images[name])
            height, width = image.shape[:2]
            for angle, shift, scale in ((-6, -16, .95), (-3, -8, 1.0), (3, 8, 1.0), (6, 16, 1.05)):
                with self.subTest(name=name, angle=angle):
                    transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
                    transform[:, 2] += (shift, -shift / 2)
                    frame = cv2.warpAffine(image, transform, (width, height), borderMode=cv2.BORDER_REFLECT_101)
                    observed = self.engine.observe(frame)
                    self.assertIsNotNone(observed.embedding, observed.message)
                    score = profile_similarity(observed.embedding, enrolled)
                    if name == "obama2.jpg":
                        self.assertEqual(observed.attention.eyes, "open")
                        self.assertGreater(score, DEFAULT_THRESHOLD)
                    else:
                        # Reject the distractor by identity even if its rotated
                        # eye measurements are uncertain.
                        self.assertLess(score, DEFAULT_THRESHOLD)

    def test_blank_and_multiple_faces_are_rejected(self):
        blank = self.engine.observe(np.full((480, 640, 3), 120, dtype=np.uint8))
        self.assertIsNone(blank.embedding)
        self.assertEqual(blank.face_count, 0)
        original = decode_image(self.images["obama.jpg"])
        scaled = cv2.resize(original, (400, 500))
        group = self.engine.observe(np.hstack([scaled, scaled]))
        self.assertEqual(group.face_count, 2)
        self.assertIsNone(group.embedding)

    def test_real_enrollment_and_repeated_photos_never_unlock(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SandboxService(self.engine, ProfileStore(Path(folder), ephemeral=True))
            result = service.dispatch("POST", "/api/enroll", {"name": "Fixture identity", "source": "image", "images": [self.images["obama.jpg"]]})
            self.assertNotIn("embedding", result["profile"])
            attempt = service.dispatch("POST", "/api/attempts", {"source": "camera"})
            endpoint = f"/api/attempts/{attempt['id']}/frame"
            wrong = service.dispatch("POST", endpoint, {"image": self.images["biden.jpg"]})
            self.assertEqual(wrong["attempt"]["streak"], 0)
            for _ in range(12):
                matched = service.dispatch("POST", endpoint, {"image": self.images["obama2.jpg"]})
                self.assertEqual(matched["attempt"]["state"], "scanning")
            self.assertEqual(matched["attempt"]["phase"], "blink")
            image_attempt = service.dispatch("POST", "/api/attempts", {"source": "image"})
            photo = service.dispatch("POST", f"/api/attempts/{image_attempt['id']}/frame", {"image": self.images["obama2.jpg"]})
            self.assertEqual(photo["attempt"]["state"], "blocked")
            service.dispatch("DELETE", "/api/profile")
            with self.assertRaises(ApiError):
                service.dispatch("POST", endpoint, {"image": self.images["obama2.jpg"]})

    def test_enrollment_cannot_mix_identities(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProfileStore(Path(folder), ephemeral=True)
            service = SandboxService(self.engine, store)
            with self.assertRaises(ApiError):
                service.dispatch("POST", "/api/enroll", {"name": "Mixed", "source": "image", "images": [self.images["obama.jpg"], self.images["biden.jpg"]]})
            self.assertIsNone(store.profile)

    def test_landmarker_measures_open_eyes_and_mirrored_pose(self):
        attention = self.observations["obama2.jpg"].attention
        self.assertEqual(attention.eyes, "open")
        self.assertIsNotNone(attention.left_blink)
        mirrored = self.engine.observe(cv2.flip(decode_image(self.images["obama2.jpg"]), 1)).attention
        self.assertEqual(mirrored.eyes, "open")
        self.assertAlmostEqual(attention.yaw, -mirrored.yaw, delta=4)
        self.assertAlmostEqual(attention.pitch, mirrored.pitch, delta=4)


if __name__ == "__main__":
    unittest.main()
