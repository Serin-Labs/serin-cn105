#!/usr/bin/env python3
"""Version index writer tests: UI-compatible ordering, archive layout and the CLI."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("homekit_index.py")
spec = importlib.util.spec_from_file_location("homekit_index", SCRIPT)
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)

URL_028 = "https://github.com/Serin-Labs/mitsubishi-cn105-homekit/releases/tag/v0.2.8"

# [a, b, expected] with expected = cmpVer(a, b). The first block mirrors
# test/version_compare/test.js in the firmware repo, which is the contract.
VECTORS = [
    ("0.2.5", "0.2.6", -1), ("0.2.6", "0.2.5", 1), ("0.2.5", "0.2.5", 0),
    ("v0.2.5", "0.2.5", 0), ("0.2.5", "0.2.5.0", 0), ("2026.7.1", "2026.7.2", -1),
    ("0.2.6-beta.1", "0.2.6", -1), ("0.2.6", "0.2.6-beta.1", 1), ("0.2.5", "0.2.6-beta.1", -1),
    ("0.2.6-beta.2", "0.2.6-beta.10", -1), ("0.2.6-beta.1", "0.2.6-beta.2", -1),
    ("0.2.6-beta.1", "0.2.6-rc.1", -1), ("0.2.6-1", "0.2.6-beta", -1),
    ("0.2.6-beta", "0.2.6-beta.1", -1),
    ("0.2.6-beta.1-3-gabc1234", "0.2.6-beta.1", 0), ("0.2.5-7-gabc1234", "0.2.5", 0),
    ("0.0.0-dev", "0.2.5", -1),
    # Beyond that file: the rest of the brief's vectors and the parseInt corners.
    ("0.2", "0.2.0", 0),
    ("0.2.5-dirty", "0.2.5", 0),
    ("v0.2.5-7-gabc1234-dirty", "0.2.5", 0),
    ("0.2.5-7-gabc123", "0.2.5", -1),           # six hex digits is no git tail, so a prerelease
    ("0.2.3a", "0.2.3", 0),                     # parseInt('3a') is 3
    ("0.x.1", "0.0.1", 0),                      # parseInt('x') is NaN, so 0
    ("", "0", 0),
    ("0.10.0", "0.9.0", 1),
]


class IndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "firmware" / "homekit" / "versions.json"

    def load(self):
        return json.loads(self.path.read_text())

    def test_cmp_versions_matches_the_ui_contract(self):
        for a, b, want in VECTORS:
            self.assertEqual(index.cmp_versions(a, b), want, (a, b))
            self.assertEqual(index.cmp_versions(b, a), -want, (b, a))

    def test_archive_path_layout(self):
        self.assertEqual(index.archive_path("0.2.8", "nanoc6"), "archive/0.2.8/nanoc6/firmware.bin")

    def test_upsert_creates_index_and_archive(self):
        changed = index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"c6", "m5atoms3-lite": b"s3"})
        self.assertTrue(changed)
        data = self.load()
        self.assertEqual(data["name"], "Mitsubishi HomeKit Controller")
        entry = data["versions"][0]
        self.assertEqual(entry["builds"]["nanoc6"],
                         {"path": "archive/0.2.8/nanoc6/firmware.bin", "sha256": hashlib.sha256(b"c6").hexdigest()})
        self.assertEqual((self.path.parent / "archive/0.2.8/nanoc6/firmware.bin").read_bytes(), b"c6")
        self.assertEqual((self.path.parent / "archive/0.2.8/m5atoms3-lite/firmware.bin").read_bytes(), b"s3")

    def test_file_format_and_key_order(self):
        index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"c6", "m5atoms3-lite": b"s3"})
        text = self.path.read_text()
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(json.loads(text), indent=2) + "\n")
        data = json.loads(text)
        self.assertEqual(list(data), ["name", "versions"])
        entry = data["versions"][0]
        self.assertEqual(list(entry), ["version", "date", "release_url", "builds"])
        self.assertEqual(list(entry["builds"]), ["m5atoms3-lite", "nanoc6"])
        self.assertEqual(list(entry["builds"]["nanoc6"]), ["path", "sha256"])
        self.assertRegex(entry["builds"]["nanoc6"]["sha256"], r"^[0-9a-f]{64}$")

    def test_upsert_is_idempotent_and_keeps_the_first_date(self):
        index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"c6"})
        before = self.path.read_bytes()
        self.assertFalse(index.upsert(self.path, "0.2.8", "2026-11-01", URL_028, {"nanoc6": b"c6"}))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.load()["versions"][0]["date"], "2026-10-14")

    def test_upsert_merges_boards_into_an_existing_version(self):
        index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"c6"})
        self.assertTrue(index.upsert(self.path, "0.2.8", "2026-10-15", URL_028, {"m5atoms3-lite": b"s3"}))
        versions = self.load()["versions"]
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["date"], "2026-10-14")
        self.assertEqual(list(versions[0]["builds"]), ["m5atoms3-lite", "nanoc6"])
        self.assertEqual(versions[0]["builds"]["nanoc6"]["sha256"], hashlib.sha256(b"c6").hexdigest())

    def test_upsert_replaces_a_changed_image(self):
        index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"old"})
        self.assertTrue(index.upsert(self.path, "0.2.8", "2026-10-14", URL_028, {"nanoc6": b"new"}))
        self.assertEqual(self.load()["versions"][0]["builds"]["nanoc6"]["sha256"], hashlib.sha256(b"new").hexdigest())
        self.assertEqual((self.path.parent / "archive/0.2.8/nanoc6/firmware.bin").read_bytes(), b"new")

    def test_versions_sort_newest_first_with_prerelease_below_release(self):
        for v in ("0.2.6-beta.4", "0.2", "0.2.6", "0.2.9-beta.1", "0.2.8"):
            index.upsert(self.path, v, "2026-10-01", URL_028, {"nanoc6": v.encode()})
        self.assertEqual([e["version"] for e in self.load()["versions"]],
                         ["0.2.9-beta.1", "0.2.8", "0.2.6", "0.2.6-beta.4", "0.2"])

    def test_insertion_order_does_not_change_the_file(self):
        order = ("0.2.8", "0.2", "0.2.0", "0.2.6")
        other = self.dir / "other" / "versions.json"
        for v in order:
            index.upsert(self.path, v, "2026-10-01", URL_028, {"nanoc6": v.encode()})
        for v in reversed(order):
            index.upsert(other, v, "2026-10-01", URL_028, {"nanoc6": v.encode()})
        self.assertEqual(self.path.read_bytes(), other.read_bytes())

    def test_unsafe_version_or_board_is_refused_before_anything_is_written(self):
        for version, board in (("../x", "nanoc6"), ("0.2.8", "../x"), ("0.2.8", "a/b"), ("", "nanoc6"), ("0.2.8", "")):
            with self.assertRaises(ValueError, msg=(version, board)):
                index.upsert(self.path, version, "2026-10-14", URL_028, {board: b"x"})
        self.assertFalse(self.path.exists())
        self.assertFalse((self.dir / "x").exists())

    def test_cli_add_writes_the_entry(self):
        c6, s3 = self.dir / "c6.bin", self.dir / "s3.bin"
        c6.write_bytes(b"c6")
        s3.write_bytes(b"s3")
        elsewhere = self.dir / "elsewhere"
        elsewhere.mkdir()
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "add", "--index", str(self.path), "--version", "0.2.8",
             "--date", "2026-10-14", "--release-url", URL_028,
             "--build", f"nanoc6={c6}", "--build", f"m5atoms3-lite={s3}"],
            cwd=elsewhere, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        entry = self.load()["versions"][0]
        self.assertEqual(entry["version"], "0.2.8")
        self.assertEqual(entry["release_url"], URL_028)
        self.assertEqual(entry["builds"]["m5atoms3-lite"]["sha256"], hashlib.sha256(b"s3").hexdigest())
        self.assertEqual((self.path.parent / "archive/0.2.8/nanoc6/firmware.bin").read_bytes(), b"c6")

    def test_cli_rejects_a_malformed_build_argument(self):
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "add", "--index", str(self.path), "--version", "0.2.8",
             "--date", "2026-10-14", "--release-url", URL_028, "--build", "nanoc6"],
            capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
