#!/usr/bin/env python3
"""Release contract tests with real files, ESP images and disposable RSA keys."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from esptool.bin_image import ELFSection, ESP32S3FirmwareImage, ImageSegment

spec = importlib.util.spec_from_file_location("validator", Path(__file__).with_name("validate-manifests.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_keys = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp_keys.cleanup)
        cls.keys = Path(cls.tmp_keys.name)
        for name in ("release", "wrong"):
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            (cls.keys / f"{name}.pem").write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (cls.keys / f"{name}.pub").write_bytes(key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        cls.app = cls.make_app()
        cls.wrong_app = cls.make_app(key="wrong")
        cls.next_app = cls.make_app(version=b"0.1.7")
        image = ESP32S3FirmwareImage()
        image.segments = [ELFSection(b"boot", 0x3fc88000, bytes(64))]
        image.save(str(cls.keys / "boot.bin"))
        cls.bootloader = (cls.keys / "boot.bin").read_bytes()

    @classmethod
    def make_app(cls, version=b"0.1.6", key="release"):
        desc = struct.pack("<IIII32s32s16s16s32s32s80x", 0xABCD5432, 0, 0, 0,
                           version, b"serin_link", b"12:00:00", b"Sep 18 2026", b"v5.5.4", bytes(32))
        image = ESP32S3FirmwareImage()
        image.segments = [ImageSegment(0x3c000020, desc)]
        image.save(str(cls.keys / "unsigned.bin"))
        subprocess.run([sys.executable, "-m", "espsecure", "sign_data", "--version", "2",
                        "--keyfile", str(cls.keys / f"{key}.pem"), "--output", str(cls.keys / "app.bin"),
                        str(cls.keys / "unsigned.bin")], check=True, capture_output=True)
        return (cls.keys / "app.bin").read_bytes()

    @classmethod
    def factory_bytes(cls, app=None, change_partition=False):
        # Exact current Link geometry, encoded independently of the validator.
        entries = [("nvs", 1, 2, 0x9000, 0x6000), ("otadata", 1, 0, 0xf000, 0x2000),
                   ("phy_init", 1, 1, 0x11000, 0x1000), ("ota_0", 0, 16, 0x20000, 0x400000),
                   ("ota_1", 0, 17, 0x420000, 0x400000)]
        if change_partition:
            entries[-1] = ("ota_1", 0, 17, 0x210000, 0x400000)  # overlaps ota_0
        table = b"".join(struct.pack("<2sBBII16sI", b"\xaa\x50", typ, sub, offset, size,
                                    name.encode(), 0) for name, typ, sub, offset, size in entries)
        table += b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(table).digest()
        data = bytearray(b"\xff" * 0x20000)
        data[:len(cls.bootloader)] = cls.bootloader
        data[0x8000:0x8000 + len(table)] = table
        return bytes(data) + (app if app is not None else cls.app)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.legacy_index = self.root / "legacy.json"
        self.legacy_index.write_text("[]")
        for name, value in (("ROOT", self.root), ("PUBLIC_KEY", self.keys / "release.pub"),
                            ("LEGACY_INDEX", self.legacy_index)):
            p = patch.object(validator, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        self.web_path, self.web = self.write_web()

    def write_web(self):
        path = self.root / "firmware/esphome/manifest.json"
        path.parent.mkdir(parents=True)
        (path.parent / "firmware.bin").write_bytes(b"test firmware")
        manifest = {"name": "ESPHome", "version": "2026.7.4", "builds": [
            {"chipFamily": "ESP32-S3", "board": "m5atoms3-lite",
             "sha256": hashlib.sha256(b"test firmware").hexdigest(),
             "parts": [{"path": "firmware.bin", "offset": 0}]}]}
        path.write_text(json.dumps(manifest))
        return path, manifest

    def write_link(self, factory=False, data=None, legacy=False):
        folder = self.root / "firmware/link"
        if not factory and not legacy:
            folder /= "ota/stable"
        folder.mkdir(parents=True, exist_ok=True)
        if data is None:
            data = self.factory_bytes() if factory else self.app
        asset = "factory.bin" if factory else "link15-app.bin"
        (folder / asset).write_bytes(data)
        manifest = {"name": "Link", "version": "0.1.6", "builds": [{
            "board": "viewe15" if factory else "link15", "path": asset,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
        if factory:
            manifest["dirty"] = False
        path = folder / ("factory-manifest.json" if factory else "manifest.json")
        path.write_text(json.dumps(manifest))
        return path, manifest

    def write_multipart(self):
        path, manifest = self.web_path, self.web
        build = manifest["builds"][0]
        build["parts"] = []
        for name, offset in (("bootloader.bin", 0), ("partitions.bin", 32768),
                             ("boot_app0.bin", 57344), ("firmware.bin", 65536)):
            asset = path.parent / name
            if not asset.exists():
                asset.write_bytes(name.encode())
            build["parts"].append({"path": name, "offset": offset,
                                   "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()})
        path.write_text(json.dumps(manifest))
        return path, manifest

    def test_multipart_checks_every_file_before_publication(self):
        path, manifest = self.write_multipart()
        code, output = self.run_check(path)
        self.assertEqual(code, 0, output)
        for part in manifest["builds"][0]["parts"]:
            with self.subTest(part=part["path"]):
                asset = path.parent / part["path"]
                original = asset.read_bytes()
                asset.write_bytes(b"corrupted download")
                self.rejects(path, contains="sha256 does not match")
                asset.write_bytes(original)

    def test_multipart_requires_every_part_hash(self):
        path, manifest = self.write_multipart()
        parts = manifest["builds"][0]["parts"]
        for part in parts:
            with self.subTest(part=part["path"]):
                saved = part.pop("sha256")
                path.write_text(json.dumps(manifest))
                self.rejects(path, contains="sha256")
                part["sha256"] = saved

    def test_single_merged_image_checks_optional_part_hash(self):
        path, manifest = self.web_path, self.web
        manifest["builds"][0]["parts"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
        self.rejects(path, contains="sha256 does not match")

    def run_check(self, *args):
        output = io.StringIO()
        if hasattr(validator, "errors"):
            validator.errors.clear()
        with patch.object(sys, "argv", ["validate-manifests.py", *map(str, args)]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                code = validator.main()
            except SystemExit as error:
                code = error.code
        return code, output.getvalue()

    def rejects(self, *args, contains=None):
        try:
            code, output = self.run_check(*args)
        except Exception as error:
            self.fail(f"Validator crashed instead of reporting an invalid manifest: {error}")
        self.assertNotEqual(code, 0, output)
        if contains:
            self.assertIn(contains, output)

    def test_factory_is_discovered_and_hash_checked(self):
        path, manifest = self.write_link(factory=True)
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("2 manifests validated", output)
        manifest["builds"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
        self.rejects(contains="sha256")

    def test_plaintext_channel_and_factory_are_discovered_without_orphan_warning(self):
        self.write_link()
        self.write_link(factory=True)
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("3 manifests validated", output)
        self.assertNotIn("not referenced", output)

    def test_unreferenced_link_file_fails_but_other_products_only_warn(self):
        self.write_link(factory=True)
        stale = self.root / "firmware/link/serin_dial_viewe15_factory.bin"
        stale.write_bytes(b"factory image under a retired name")
        self.rejects(contains="Link file not referenced")
        stale.unlink()
        (self.root / "firmware/esphome/old.bin").write_bytes(b"stray")
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("::warning::", output)

    def test_link_wrong_key_and_embedded_version_are_rejected_after_hash_passes(self):
        for factory in (False, True):
            for app, reason in ((self.wrong_app, "signature"), (self.next_app, "version")):
                with self.subTest(factory=factory, reason=reason):
                    self.write_link(factory=factory, data=self.factory_bytes(app) if factory else app)
                    self.rejects(contains=reason)

    def test_signature_must_be_at_the_offset_used_by_the_device(self):
        unsigned = self.keys / "overpadded.bin"
        unsigned.write_bytes(self.app[:-4096] + b"\xff" * 4096)
        signed = self.keys / "overpadded-signed.bin"
        subprocess.run([sys.executable, "-m", "espsecure", "sign_data", "--version", "2",
                        "--keyfile", str(self.keys / "release.pem"), "--output", str(signed),
                        str(unsigned)], check=True, capture_output=True)
        self.write_link(data=signed.read_bytes())
        self.rejects(contains="signature")

    def test_unsigned_or_corrupted_link_apps_fail_even_with_updated_manifest_hash(self):
        corrupt_payload = bytearray(self.app)
        corrupt_payload[100] ^= 1
        corrupt_signature = bytearray(self.app)
        corrupt_signature[-4096 + 812] ^= 1
        for data in (self.app[:-4096], corrupt_payload, corrupt_signature):
            with self.subTest(length=len(data)):
                self.write_link(data=data)
                self.rejects(contains="signature")

    def test_link_directory_cannot_bypass_checks_using_controller_shape(self):
        path, _ = self.write_link(data=self.wrong_app)
        manifest = copy.deepcopy(self.web)
        manifest["builds"][0].update(sha256=hashlib.sha256(self.wrong_app).hexdigest(),
                                    parts=[{"path": "link15-app.bin", "offset": 0}])
        path.write_text(json.dumps(manifest))
        self.rejects(contains="format")

    def test_factory_geometry_and_partition_checksum_are_checked(self):
        bad_checksum = bytearray(self.factory_bytes())
        bad_checksum[0x8000 + 5 * 32 + 16] ^= 1  # MD5 after five partition entries
        cases = {"overlap": self.factory_bytes(change_partition=True),
                 "bad magic": self.factory_bytes()[:0x8000] + b"\0" + self.factory_bytes()[0x8001:],
                 "bad checksum": bad_checksum}
        for name, data in cases.items():
            with self.subTest(name=name):
                self.write_link(factory=True, data=data)
                self.rejects(contains="partition")

    def test_factory_dirty_provenance_is_required_and_release_default_rejects_dirty(self):
        path, manifest = self.write_link(factory=True)
        for value in (None, "false", True):
            with self.subTest(dirty=value):
                candidate = copy.deepcopy(manifest)
                if value is None:
                    del candidate["dirty"]
                else:
                    candidate["dirty"] = value
                path.write_text(json.dumps(candidate))
                self.rejects(contains="dirty")
        code, output = self.run_check("--allow-dirty")
        self.assertEqual(code, 0, output)

    def test_invalid_json_shapes_report_errors_without_tracebacks(self):
        cases = [None, [], "text", 1, {}, {"name": "test", "version": "1.0.0", "builds": True},
                 {"name": "test", "version": "1.0.0", "builds": [None]}]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.web_path.write_text(json.dumps(manifest))
                self.rejects()

    def test_duplicate_json_keys_are_rejected(self):
        self.web_path.write_text(json.dumps(self.web).replace('"version": "2026.7.4"',
                                                             '"version": "wrong", "version": "2026.7.4"'))
        self.rejects(contains="duplicate")

    def test_build_schema_rejects_missing_or_invalid_fields(self):
        variants = [dict(parts=[]), dict(parts=[None]), dict(parts=[{"path": "firmware.bin", "offset": True}]),
                    dict(parts=[{"path": "firmware.bin", "offset": -4096}]),
                    dict(parts=[{"path": "firmware.bin", "offset": 1}]),
                    dict(chipFamily="ESP8266"), dict(board="viewe15"), dict(sha256="bad")]
        for update in variants:
            with self.subTest(update=update):
                manifest = copy.deepcopy(self.web)
                manifest["builds"][0].update(update)
                self.web_path.write_text(json.dumps(manifest))
                self.rejects()

    def test_manifest_metadata_is_typed_and_channel_matches_version(self):
        for update in ({"version": 123}, {"version": "0.1.7-beta.1"}, {"channel": "beta"},
                       {"channel": "nightly"}, {"name": []}, {"release_url": "http://example.com"},
                       {"new_install_prompt_erase": "false"}):
            with self.subTest(update=update):
                self.web_path.write_text(json.dumps({**self.web, **update}))
                self.rejects()

    def test_web_artifact_hash_and_existence_are_checked(self):
        artifact = self.web_path.parent / "firmware.bin"
        artifact.write_bytes(b"corrupted firmware")
        self.rejects(contains="sha256")
        artifact.unlink()
        self.rejects(contains="missing")

    def test_paths_cannot_escape_or_use_url_syntax(self):
        (self.web_path.parent.parent / "outside.bin").write_bytes(b"test firmware")
        for value in ("../outside.bin", "/etc/passwd", "https://example.com/a.bin", "firmware.bin?x=1",
                      "firmware.bin#x", "../esphome/firmware.bin", "firmware.bin%00", "./firmware.bin"):
            with self.subTest(path=value):
                manifest = copy.deepcopy(self.web)
                manifest["builds"][0]["parts"][0]["path"] = value
                self.web_path.write_text(json.dumps(manifest))
                self.rejects(contains="path")
        (self.web_path.parent / "escape.bin").symlink_to(self.web_path.parent.parent / "outside.bin")
        manifest["builds"][0]["parts"][0]["path"] = "escape.bin"
        self.web_path.write_text(json.dumps(manifest))
        self.rejects(contains="path")

    def test_duplicate_boards_and_overlapping_flash_parts_are_rejected(self):
        manifest = copy.deepcopy(self.web)
        manifest["builds"].append(copy.deepcopy(manifest["builds"][0]))
        self.web_path.write_text(json.dumps(manifest))
        self.rejects(contains="duplicate")
        manifest = copy.deepcopy(self.web)
        (self.web_path.parent / "bootloader.bin").write_bytes(b"boot")
        manifest["builds"][0]["parts"].append({"path": "bootloader.bin", "offset": 0})
        self.web_path.write_text(json.dumps(manifest))
        self.rejects(contains="overlap")

    def test_legacy_encrypted_artifact_must_match_archived_bytes_and_metadata(self):
        path, manifest = self.write_link(data=b"ciphertext", legacy=True)
        build = manifest["builds"][0]
        build.update(size=8192, enc_size=10, sha256="1" * 64)
        path.write_text(json.dumps(manifest))
        self.legacy_index.write_text(json.dumps([{"version": "0.1.6", "build": build,
                                                  "ciphertext_sha256": hashlib.sha256(b"ciphertext").hexdigest()}]))
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("legacy", output.lower())
        (path.parent / build["path"]).write_bytes(b"bad-bytes!")
        self.rejects(contains="legacy")
        (path.parent / build["path"]).write_bytes(b"ciphertext")
        build["sha256"] = "2" * 64
        path.write_text(json.dumps(manifest))
        self.rejects(contains="legacy")

    def test_adding_enc_size_cannot_bypass_signature_checks(self):
        path, manifest = self.write_link(data=self.wrong_app)
        manifest["builds"][0]["enc_size"] = len(self.wrong_app)
        path.write_text(json.dumps(manifest))
        self.rejects(contains="legacy")

    def test_plaintext_cannot_replace_the_legacy_encrypted_feed(self):
        self.write_link(legacy=True)
        self.rejects(contains="legacy encrypted")

    def test_plaintext_channel_metadata_must_match_its_directory(self):
        path, manifest = self.write_link()
        manifest.update(version="0.1.7-beta.1", channel="beta")
        path.write_text(json.dumps(manifest))
        self.rejects(contains="channel directory")

    def test_explicit_manifest_outside_repo_is_validated_before_publication(self):
        path, manifest = self.write_link(factory=True)
        self.web_path.write_text("invalid JSON")  # must not be scanned for an explicit file
        code, output = self.run_check(path)
        self.assertEqual(code, 0, output)
        manifest["builds"][0]["size"] += 1
        path.write_text(json.dumps(manifest))
        self.rejects(path, contains="size")


if __name__ == "__main__":
    unittest.main()
