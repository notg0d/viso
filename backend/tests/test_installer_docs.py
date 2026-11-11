"""Bundled installer guides must not require a checkout to follow their links."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("installer_docs", Path(__file__).resolve().parents[2] / "scripts" / "package-installer-docs.py")
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)
COMMIT = "a" * 40


class InstallerDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.bundle = Path(self.temporary.name) / "payload"
        (self.root / "docs").mkdir(parents=True)
        (self.bundle / "docs").mkdir(parents=True)
        self.guide = self.bundle / "docs" / "guide.md"

    def rewrite(self, text):
        self.guide.write_text(text, encoding="utf-8")
        PACKAGER.rewrite_documentation(self.root, self.bundle, COMMIT)
        return self.guide.read_text(encoding="utf-8")

    def test_bundled_guides_fragments_and_external_links_remain_unchanged(self):
        (self.bundle / "docs" / "other.md").write_text("# Topic", encoding="utf-8")
        text = "[guide](other.md#topic) [self](#topic) [web](https://example.com/)"
        self.assertEqual(self.rewrite(text), text)

    def test_source_files_directories_and_fragments_are_commit_pinned(self):
        (self.root / "README.md").write_text("# Overview", encoding="utf-8")
        (self.root / "desktop").mkdir()
        text = self.rewrite('[overview](../README.md#overview "title") [source](../desktop/)')
        self.assertIn(f'/blob/{COMMIT}/README.md#overview "title"', text)
        self.assertIn(f"/tree/{COMMIT}/desktop", text)

    def test_html_and_angle_targets_are_rewritten_but_code_examples_are_not(self):
        (self.root / "source file.md").write_text("# Source", encoding="utf-8")
        text = self.rewrite('[source](<../source file.md>)\n<a href="../source%20file.md">source</a>\n```text\n[example](../missing.md)\n```\n')
        self.assertIn(f"/blob/{COMMIT}/source%20file.md", text)
        self.assertIn("[example](../missing.md)", text)

    def test_missing_and_outside_source_targets_are_rejected(self):
        for target in "../missing.md", "../../outside.md":
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.rewrite(f"[invalid]({target})")

    def test_malformed_source_commit_is_rejected(self):
        self.guide.write_text("# Guide", encoding="utf-8")
        with self.assertRaises(ValueError):
            PACKAGER.rewrite_documentation(self.root, self.bundle, "main")
