import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from backend.viso.server import ROOT, SandboxServer, main
from backend.viso.service import SandboxService
from backend.viso.storage import ProfileStore


class BrowserHostTests(unittest.TestCase):
    def test_entry_point_serves_nested_browser_build_in_memory_only_mode(self):
        with patch("backend.viso.server.FaceEngine") as engine, patch("backend.viso.server.SandboxServer") as server, patch("sys.argv", ["viso", "--ephemeral"]), contextlib.redirect_stdout(io.StringIO()):
            server.return_value.serve_forever.side_effect = KeyboardInterrupt
            main()
        address, service, dist = server.call_args.args
        self.assertEqual(address, ("127.0.0.1", 8765))
        self.assertEqual(dist, ROOT / "experiments" / "browser" / "dist")
        self.assertFalse(service.store.persistent)
        server.return_value.server_close.assert_called_once()
        engine.return_value.close.assert_called_once()

    def test_missing_build_is_actionable_and_built_index_is_served(self):
        with tempfile.TemporaryDirectory() as folder:
            dist = Path(folder) / "experiments" / "browser" / "dist"
            dist.mkdir(parents=True)
            service = SandboxService(None, ProfileStore(Path(folder), ephemeral=True), "Test engine")
            server = SandboxServer(("127.0.0.1", 0), service, dist)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/"
            try:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(url, timeout=5)
                with caught.exception as response:
                    self.assertEqual(response.code, 503)
                    message = response.read().decode()
                    self.assertIn("npm --prefix experiments/browser run build", message)
                    self.assertIn("native desktop app does not use this host", message)
                index = b"<!doctype html><title>Historical browser bench</title>"
                (dist / "index.html").write_bytes(index)
                with urlopen(url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), index)
                    self.assertEqual(response.headers["Content-Type"], "text/html")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertFalse((Path(folder) / "profile.dpapi").exists())
