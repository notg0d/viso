"""Dependency packaging regressions; all inputs are synthetic temporary files."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("package_runtime", Path(__file__).resolve().parents[2] / "scripts" / "package-runtime.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class Distribution:
    def __init__(self, site, version, files, requires=()):
        self.site, self.version, self.files, self.requires = site, version, files, requires

    def locate_file(self, relative):
        return self.site / relative


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.site = self.root / ".venv" / "Lib" / "site-packages"
        self.site.mkdir(parents=True)
        self.destination = self.root / "runtime"
        self.destination.mkdir()
        (self.root / "requirements.txt").write_text("rootpkg==1.0\n")

    def distribution(self, files, version="1.0", requires=()):
        for relative in files:
            path = self.site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic")
        return Distribution(self.site, version, files, requires)

    def run_package(self, distributions):
        with patch.object(packager.sys, "prefix", str(self.root / ".venv")), \
                patch.object(packager.metadata, "distribution", side_effect=distributions.__getitem__):
            packager.package(self.root, self.destination)

    def test_only_dependency_closure_is_copied_with_notices_and_no_caches_tests_or_local_urls(self):
        root = self.distribution(["rootpkg/__init__.py", "rootpkg/tests/test_example.py", "rootpkg/__pycache__/cache.pyc",
                                  "rootpkg-1.0.dist-info/LICENSE", "rootpkg-1.0.dist-info/direct_url.json"],
                                 requires=["child>=2.0", "not-needed; extra == 'dev'"])
        child = self.distribution(["child/__init__.py", "child-2.0.dist-info/LICENSE"], version="2.0")
        self.distribution(["unrelated.py", "~backup/__init__.py"])
        self.run_package({"rootpkg": root, "child": child})
        copied = {p.relative_to(self.destination).as_posix() for p in self.destination.rglob("*") if p.is_file()}
        self.assertEqual(copied, {"Lib/site-packages/rootpkg/__init__.py", "Lib/site-packages/rootpkg-1.0.dist-info/LICENSE",
                                  "Lib/site-packages/child/__init__.py", "Lib/site-packages/child-2.0.dist-info/LICENSE", "packages.json"})
        self.assertEqual(json.loads((self.destination / "packages.json").read_text())["dependencies"], {"child": "2.0", "rootpkg": "1.0"})

    def test_pin_mismatch_fails(self):
        with self.assertRaisesRegex(RuntimeError, "does not satisfy"):
            self.run_package({"rootpkg": self.distribution(["rootpkg.py"], version="1.1")})

    def test_missing_record_fails(self):
        with self.assertRaisesRegex(RuntimeError, "file manifest"):
            self.run_package({"rootpkg": Distribution(self.site, "1.0", None)})

    def test_missing_runtime_file_fails(self):
        with self.assertRaisesRegex(RuntimeError, "Missing installed runtime file"):
            self.run_package({"rootpkg": Distribution(self.site, "1.0", ["absent.py"])})

    def test_outside_environment_dependency_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "outside the project's environment"):
            self.run_package({"rootpkg": Distribution(self.root, "1.0", ["outside.py"])})

    def test_source_environment_is_required(self):
        with self.assertRaisesRegex(RuntimeError, "project's .venv Python"):
            packager.package(self.root, self.destination)


if __name__ == "__main__":
    unittest.main()
