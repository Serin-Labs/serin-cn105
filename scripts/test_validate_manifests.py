#!/usr/bin/env python3
"""Release contract tests with real files, ESP images and disposable RSA keys."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
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
        cls.apps = {"viewe15": cls.make_app(project=b"serin_link_viewe15"),
                    "viewe21": cls.make_app(project=b"serin_link_viewe21")}
        cls.app = cls.apps["viewe15"]
        cls.wrong_app = cls.make_app(key="wrong")
        cls.next_app = cls.make_app(version=b"0.1.7")
        image = ESP32S3FirmwareImage()
        image.segments = [ELFSection(b"boot", 0x3fc88000, bytes(64))]
        image.save(str(cls.keys / "boot.bin"))
        cls.bootloader = (cls.keys / "boot.bin").read_bytes()

    @classmethod
    def make_app(cls, version=b"0.1.6", key="release", project=b"serin_link_viewe15"):
        desc = struct.pack("<IIII32s32s16s16s32s32s80x", 0xABCD5432, 0, 0, 0,
                           version, project, b"12:00:00", b"Sep 18 2026", b"v5.5.4", bytes(32))
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
        for name, value in (("ROOT", self.root), ("PUBLIC_KEY", self.keys / "release.pub")):
            p = patch.object(validator, name, value)
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

    def write_link(self, factory=False, data=None, board="viewe15"):
        folder = self.root / "firmware/link"
        if not factory:
            folder /= "ota/stable"
        folder.mkdir(parents=True, exist_ok=True)
        if data is None:
            data = self.factory_bytes(self.apps[board]) if factory else self.apps[board]
        asset = "factory.bin" if factory else "link15-app.bin"
        (folder / asset).write_bytes(data)
        manifest = {"name": "Link", "version": "0.1.6", "builds": [{
            "board": board if factory else {"viewe15": "link15", "viewe21": "link21"}[board], "path": asset,
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

    def test_board_specific_images_validate_for_each_ota_and_factory_board(self):
        for factory in (False, True):
            for board in ("viewe15", "viewe21"):
                with self.subTest(factory=factory, board=board):
                    path, _ = self.write_link(factory=factory, board=board)
                    code, output = self.run_check(path)
                    self.assertEqual(code, 0, output)

    def test_signed_app_project_must_match_manifest_board_after_hash_passes(self):
        # Both images have trusted signatures, valid ESP checksums and the
        # manifest's version: only the signed board identity is wrong.
        for factory in (False, True):
            for target, actual in (("viewe15", "viewe21"), ("viewe21", "viewe15")):
                with self.subTest(factory=factory, target=target):
                    app = self.apps[actual]
                    path, _ = self.write_link(factory=factory, board=target,
                                              data=self.factory_bytes(app) if factory else app)
                    self.rejects(path, contains="project")

    def test_project_name_must_be_specific_ascii_and_terminated(self):
        cases = {"generic": b"serin_link", "empty": b"", "unknown": b"serin_link_viewe15_extra",
                 "non-ASCII": b"serin_link_viewe15\xff", "unterminated": b"serin_link_viewe15" + b"x" * 14}
        for name, project in cases.items():
            app = self.make_app(project=project)
            for factory in (False, True):
                with self.subTest(factory=factory, project=name):
                    path, _ = self.write_link(factory=factory,
                                              data=self.factory_bytes(app) if factory else app)
                    self.rejects(path, contains="project")

    def test_factory_split_parts_do_not_bypass_board_check(self):
        path, _ = self.write_factory_parts(data=self.factory_bytes(self.apps["viewe21"]))
        self.rejects(path, contains="project")

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

    def test_encrypted_format_is_retired_and_cannot_bypass_signature_checks(self):
        path, manifest = self.write_link(data=self.wrong_app)
        manifest["builds"][0]["enc_size"] = len(self.wrong_app)
        path.write_text(json.dumps(manifest))
        self.rejects(contains="retired")

    def test_retired_encrypted_feed_paths_are_rejected(self):
        path, manifest = self.write_link()
        old = self.root / "firmware/link/manifest.json"
        (old.parent / manifest["builds"][0]["path"]).write_bytes(self.app)
        old.write_text(json.dumps(manifest))
        self.rejects(contains="unknown Link OTA channel directory")

    def write_factory_parts(self, folder=None, data=None, version="0.1.6"):
        """A factory manifest whose build also lists the split parts, sliced
        from the merged image the way publish_fw.py does."""
        folder = folder or self.root / "firmware/link"
        folder.mkdir(parents=True, exist_ok=True)
        data = data if data is not None else self.factory_bytes()
        (folder / "factory.bin").write_bytes(data)
        table_end = 0x8000 + data[0x8000:0x9000].index(b"\xeb\xeb") + 32
        slices = {"bootloader.bin": (0, data[:len(self.bootloader)]),
                  "partition-table.bin": (0x8000, data[0x8000:table_end]),
                  "otadata-blank.bin": (0xf000, data[0xf000:0x11000]),
                  "app.bin": (0x20000, data[0x20000:])}
        parts = []
        for name, (offset, chunk) in slices.items():
            (folder / name).write_bytes(chunk)
            parts.append({"path": name, "offset": offset, "sha256": hashlib.sha256(chunk).hexdigest()})
        manifest = {"name": "Link", "version": version, "dirty": False, "builds": [{
            "board": "viewe15", "path": "factory.bin", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "parts": parts}]}
        if "-" in version:
            manifest["channel"] = "beta"
        path = folder / "factory-manifest.json"
        path.write_text(json.dumps(manifest))
        return path, manifest

    def test_factory_split_parts_validate_and_are_not_orphans(self):
        self.write_factory_parts()
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("split parts", output)
        self.assertNotIn("not referenced", output)

    def test_factory_part_must_match_the_merged_image(self):
        path, manifest = self.write_factory_parts()
        other = self.next_app
        (path.parent / "app.bin").write_bytes(other)
        manifest["builds"][0]["parts"][3]["sha256"] = hashlib.sha256(other).hexdigest()
        path.write_text(json.dumps(manifest))
        self.rejects(contains="differs from the merged image")

    def test_factory_parts_cannot_write_over_the_settings_partition(self):
        path, manifest = self.write_factory_parts()
        part = manifest["builds"][0]["parts"][2]
        part["offset"] = 0x9000
        path.write_text(json.dumps(manifest))
        self.rejects(contains="offsets")
        # A bootloader part padded on through nvs keeps a legal offset but not a legal reach.
        path, manifest = self.write_factory_parts()
        padded = self.factory_bytes()[:0xa000]
        (path.parent / "bootloader.bin").write_bytes(padded)
        manifest["builds"][0]["parts"][0]["sha256"] = hashlib.sha256(padded).hexdigest()
        path.write_text(json.dumps(manifest))
        self.rejects(contains="overruns")

    def test_factory_parts_must_cover_everything_the_merged_image_writes(self):
        path, manifest = self.write_factory_parts()
        short = (path.parent / "app.bin").read_bytes()[:-4096]
        (path.parent / "app.bin").write_bytes(short)
        manifest["builds"][0]["parts"][3]["sha256"] = hashlib.sha256(short).hexdigest()
        path.write_text(json.dumps(manifest))
        self.rejects(contains="reassemble")

    def test_factory_otadata_part_must_blank_the_whole_partition(self):
        path, manifest = self.write_factory_parts()
        (path.parent / "otadata-blank.bin").write_bytes(b"\xff" * 0x1000)
        manifest["builds"][0]["parts"][2]["sha256"] = hashlib.sha256(b"\xff" * 0x1000).hexdigest()
        path.write_text(json.dumps(manifest))
        self.rejects(contains="otadata")

    def test_factory_parts_require_hashes(self):
        path, manifest = self.write_factory_parts()
        del manifest["builds"][0]["parts"][0]["sha256"]
        path.write_text(json.dumps(manifest))
        self.rejects(contains="sha256")

    def test_ota_manifest_cannot_carry_parts(self):
        path, manifest = self.write_link()
        manifest["builds"][0]["parts"] = []
        path.write_text(json.dumps(manifest))
        self.rejects()

    def test_beta_factory_lives_only_in_its_channel_directory(self):
        beta_app = self.make_app(version=b"0.1.7-beta.1")
        data = self.factory_bytes(app=beta_app)
        self.write_factory_parts(self.root / "firmware/link/factory/beta", data, "0.1.7-beta.1")
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        shutil.rmtree(self.root / "firmware/link/factory")
        self.write_factory_parts(data=data, version="0.1.7-beta.1")
        self.rejects(contains="channel directory")
        shutil.rmtree(self.root / "firmware/link")
        self.write_factory_parts(self.root / "firmware/link/factory/nightly")
        self.rejects(contains="unknown Link factory directory")

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

    HOMEKIT_URL = "https://github.com/akifbayram/mitsubishi-cn105-homekit/releases/tag/v{}"

    @staticmethod
    def homekit_image(version):
        return f"homekit firmware {version}".encode()

    def write_homekit_manifest(self, folder, version, channel="stable"):
        """A nanoc6 multipart controller manifest in `folder` (four parts, as write_multipart)."""
        board_dir = folder / "nanoc6"
        board_dir.mkdir(parents=True, exist_ok=True)
        parts = []
        for name, offset in (("bootloader.bin", 0), ("partitions.bin", 32768),
                             ("boot_app0.bin", 57344), ("firmware.bin", 65536)):
            data = self.homekit_image(version) if name == "firmware.bin" else name.encode()
            (board_dir / name).write_bytes(data)
            parts.append({"path": f"nanoc6/{name}", "offset": offset, "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"name": "Mitsubishi HomeKit Controller", "version": version, "channel": channel,
                    "release_url": self.HOMEKIT_URL.format(version),
                    "builds": [{"chipFamily": "ESP32-C6", "board": "nanoc6",
                                "sha256": parts[-1]["sha256"], "parts": parts}]}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def write_homekit(self, versions=("0.9.0",)):
        """The stable manifest names versions[0]; every version gets an archived
        firmware.bin and an index entry. Returns the index path and its content."""
        folder = self.root / "firmware/homekit"
        self.write_homekit_manifest(folder, versions[0])
        index = {"name": "Mitsubishi HomeKit Controller", "versions": []}
        for version in versions:
            data = self.homekit_image(version)
            path = f"archive/{version}/nanoc6/firmware.bin"
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(data)
            index["versions"].append({
                "version": version, "date": "2026-10-20", "release_url": self.HOMEKIT_URL.format(version),
                "builds": {"nanoc6": {"path": path, "sha256": hashlib.sha256(data).hexdigest()}}})
        path = folder / "versions.json"
        path.write_text(json.dumps(index))
        return path, index

    def test_homekit_index_validates_and_archive_is_not_orphaned(self):
        self.write_homekit(versions=("0.9.0", "0.8.0"))
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertNotIn("not referenced", output)

    def test_unindexed_archive_file_is_still_an_orphan_warning(self):
        self.write_homekit()
        stray = self.root / "firmware/homekit/archive/0.1.0/nanoc6/firmware.bin"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"left behind")
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("0.1.0/nanoc6/firmware.bin: not referenced", output)

    def test_index_archive_hash_is_checked(self):
        self.write_homekit(versions=("0.9.0", "0.8.0"))
        (self.root / "firmware/homekit/archive/0.8.0/nanoc6/firmware.bin").write_bytes(b"corrupted download")
        self.rejects(contains="sha256 does not match")

    def test_index_must_list_the_published_manifests(self):
        path, index = self.write_homekit(versions=("0.9.0", "0.8.0"))
        index["versions"].pop(0)
        path.write_text(json.dumps(index))
        self.rejects(contains="index is missing manifest version 0.9.0")

    def test_index_must_list_the_beta_manifest_too(self):
        path, index = self.write_homekit()
        self.write_homekit_manifest(self.root / "firmware/homekit/beta", "0.9.1-beta.1", channel="beta")
        self.rejects(contains="index is missing manifest version 0.9.1-beta.1")
        # The beta image is archived and listed, so the same layout now passes.
        data = self.homekit_image("0.9.1-beta.1")
        archived = self.root / "firmware/homekit/archive/0.9.1-beta.1/nanoc6/firmware.bin"
        archived.parent.mkdir(parents=True)
        archived.write_bytes(data)
        index["versions"].insert(0, {
            "version": "0.9.1-beta.1", "date": "2026-10-21", "release_url": self.HOMEKIT_URL.format("0.9.1-beta.1"),
            "builds": {"nanoc6": {"path": "archive/0.9.1-beta.1/nanoc6/firmware.bin",
                                  "sha256": hashlib.sha256(data).hexdigest()}}})
        path.write_text(json.dumps(index))
        code, output = self.run_check()
        self.assertEqual(code, 0, output)

    def test_index_manifest_version_is_compared_exactly(self):
        # 0.9 and 0.9.0 are the same release to cmpVer, but not the same string.
        path, index = self.write_homekit()
        index["versions"][0]["version"] = "0.9"
        index["versions"][0]["builds"]["nanoc6"]["path"] = "archive/0.9/nanoc6/firmware.bin"
        archived = self.root / "firmware/homekit/archive/0.9/nanoc6/firmware.bin"
        archived.parent.mkdir(parents=True)
        archived.write_bytes(self.homekit_image("0.9.0"))
        path.write_text(json.dumps(index))
        self.rejects(contains="index is missing manifest version 0.9.0")

    def test_index_hash_must_match_the_manifest_app(self):
        path, index = self.write_homekit(versions=("0.9.0", "0.8.0"))
        other = b"other archived bytes"
        (self.root / "firmware/homekit/archive/0.9.0/nanoc6/firmware.bin").write_bytes(other)
        index["versions"][0]["builds"]["nanoc6"]["sha256"] = hashlib.sha256(other).hexdigest()
        path.write_text(json.dumps(index))
        self.rejects(contains="index hash for 0.9.0 nanoc6 does not match manifest")

    def test_index_must_carry_every_board_the_manifest_publishes(self):
        path, index = self.write_homekit()
        manifest_path = self.root / "firmware/homekit/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        s3 = self.root / "firmware/homekit/m5atoms3-lite"
        s3.mkdir()
        parts = []
        for name, offset in (("bootloader.bin", 0), ("partitions.bin", 32768),
                             ("boot_app0.bin", 57344), ("firmware.bin", 65536)):
            (s3 / name).write_bytes(b"s3 " + name.encode())
            parts.append({"path": f"m5atoms3-lite/{name}", "offset": offset,
                          "sha256": hashlib.sha256(b"s3 " + name.encode()).hexdigest()})
        manifest["builds"].append({"chipFamily": "ESP32-S3", "board": "m5atoms3-lite",
                                   "sha256": parts[-1]["sha256"], "parts": parts})
        manifest_path.write_text(json.dumps(manifest))
        self.rejects(contains="index hash for 0.9.0 m5atoms3-lite does not match manifest")

    def test_index_accepts_a_two_component_version(self):
        self.write_homekit(versions=("0.9.0", "0.2"))
        code, output = self.run_check()
        self.assertEqual(code, 0, output)

    def test_index_rejects_bad_entries(self):
        def board(entry):
            entry["builds"]["esp32-devkit"] = entry["builds"].pop("nanoc6")

        def version(entry):
            entry["version"] = "0.8.0-beta"  # a prerelease needs a number

        def duplicate(entry):
            index["versions"].append(copy.deepcopy(entry))

        def path(entry):
            entry["builds"]["nanoc6"]["path"] = "archive/0.8.0/firmware.bin"

        def date(entry):
            entry["date"] = "2026-13-01"

        def release_url(entry):
            entry["release_url"] = "http://github.com/akifbayram/mitsubishi-cn105-homekit/releases/tag/v0.8.0"

        cases = [(board, "unknown board"), (version, "invalid index version"),
                 (duplicate, "duplicate index version 0.8.0"),
                 (path, "index path for 0.8.0 nanoc6 must be archive/0.8.0/nanoc6/firmware.bin"),
                 (date, "real YYYY-MM-DD date"), (release_url, "release_url must be an HTTPS URL")]
        for mutate, message in cases:
            with self.subTest(case=mutate.__name__):
                index_path, index = self.write_homekit(versions=("0.9.0", "0.8.0"))
                mutate(index["versions"][1])
                index_path.write_text(json.dumps(index))
                self.rejects(contains=message)

    def test_index_dates_must_be_strict_calendar_dates(self):
        for value in ("2026-02-30", "20261020", "2026-1-20", "2026-10-20T00:00:00", " 2026-10-20",
                      "２０２６-１０-２０", 20261020, None):
            with self.subTest(date=value):
                path, index = self.write_homekit()
                index["versions"][0]["date"] = value
                path.write_text(json.dumps(index))
                self.rejects(contains="real YYYY-MM-DD date")
        path, index = self.write_homekit()
        index["versions"][0]["date"] = "2028-02-29"  # leap day
        path.write_text(json.dumps(index))
        code, output = self.run_check()
        self.assertEqual(code, 0, output)

    def test_index_release_url_is_required_and_https_without_credentials(self):
        for value in (None, 7, "", "http://example.com", "ftp://example.com/x", "https://",
                      "https://user:secret@github.com/akifbayram", "https://user@github.com/akifbayram"):
            with self.subTest(release_url=value):
                path, index = self.write_homekit()
                index["versions"][0]["release_url"] = value
                path.write_text(json.dumps(index))
                self.rejects(contains="release_url must be an HTTPS URL")
        path, index = self.write_homekit()
        del index["versions"][0]["release_url"]
        path.write_text(json.dumps(index))
        self.rejects(contains="release_url must be an HTTPS URL")

    def test_index_versions_must_follow_the_release_pattern(self):
        for value in ("0", "0.9.0.1", "v0.9.0", "0.9.0-beta", "0.9.0-beta.", "0.9.0-1", "0.9.0-beta.1.2",
                      "0.9.0 ", "", "../0.9.0", "0.9.0-dirty", 9, None, ["0.9.0"]):
            with self.subTest(version=value):
                path, index = self.write_homekit()
                index["versions"][0]["version"] = value
                path.write_text(json.dumps(index))
                self.rejects(contains="invalid index version")
        for value in ("1.0", "10.20.30", "0.9.1-beta.1", "0.9.1-rc.12"):
            with self.subTest(version=value):
                self.write_homekit(versions=("0.9.0", value))
                code, output = self.run_check()
                self.assertEqual(code, 0, output)

    def test_index_shapes_report_errors_without_tracebacks(self):
        def entry(**update):
            def change(index):
                index["versions"][0].update(update)
            return change

        def builds(value):
            return entry(builds=value)

        def build(**update):
            def change(index):
                index["versions"][0]["builds"]["nanoc6"].update(update)
            return change

        def top(**update):
            return lambda index: index.update(update)

        cases = [
            ("name missing", lambda index: index.pop("name"), "name must be a nonempty string"),
            ("name blank", top(name="  "), "name must be a nonempty string"),
            ("name typed", top(name=[]), "name must be a nonempty string"),
            ("versions empty", top(versions=[]), "versions must be a nonempty array"),
            ("versions object", top(versions={}), "versions must be a nonempty array"),
            ("versions missing", lambda index: index.pop("versions"), "versions must be a nonempty array"),
            ("entry null", top(versions=[None]), "versions must be a nonempty array of objects"),
            ("entry string", top(versions=["0.9.0"]), "versions must be a nonempty array of objects"),
            ("builds empty", builds({}), "builds for 0.9.0 must be a nonempty object"),
            ("builds array", builds([]), "builds for 0.9.0 must be a nonempty object"),
            ("builds null", builds(None), "builds for 0.9.0 must be a nonempty object"),
            ("build null", builds({"nanoc6": None}), "index build for 0.9.0 nanoc6 must be an object"),
            ("build string", builds({"nanoc6": "archive/0.9.0/nanoc6/firmware.bin"}), "index build for 0.9.0 nanoc6 must be an object"),
            ("path missing", lambda index: index["versions"][0]["builds"]["nanoc6"].pop("path"),
             "must be archive/0.9.0/nanoc6/firmware.bin"),
            ("path typed", build(path=7), "must be archive/0.9.0/nanoc6/firmware.bin"),
            ("path traversal", build(path="archive/0.9.0/../0.9.0/nanoc6/firmware.bin"),
             "must be archive/0.9.0/nanoc6/firmware.bin"),
            ("sha missing", lambda index: index["versions"][0]["builds"]["nanoc6"].pop("sha256"),
             "sha256 must be 64 lowercase hexadecimal characters"),
            ("sha uppercase", build(sha256="A" * 64), "sha256 must be 64 lowercase hexadecimal characters"),
            ("sha typed", build(sha256=7), "sha256 must be 64 lowercase hexadecimal characters"),
        ]
        for label, change, message in cases:
            with self.subTest(case=label):
                index_path, index = self.write_homekit()
                change(index)
                index_path.write_text(json.dumps(index))
                self.rejects(contains=message)
        index_path, _ = self.write_homekit()
        for label, document in (("array", []), ("string", "text"), ("null", None), ("number", 1)):
            with self.subTest(case=label):
                index_path.write_text(json.dumps(document))
                self.rejects(contains="index must be an object")

    def test_index_archive_file_must_exist_and_be_nonempty(self):
        archived = self.root / "firmware/homekit/archive/0.9.0/nanoc6/firmware.bin"
        self.write_homekit()
        archived.write_bytes(b"")
        self.rejects(contains="is empty")
        archived.unlink()
        self.rejects(contains="missing")

    def test_index_duplicate_json_keys_are_rejected(self):
        path, _ = self.write_homekit()
        path.write_text(path.read_text().replace('"date": "2026-10-20"', '"date": "2026-01-01", "date": "2026-10-20"'))
        self.rejects(contains="duplicate JSON key")

    def test_index_failure_names_the_index_and_exits_nonzero(self):
        path, index = self.write_homekit()
        index["versions"][0]["date"] = "soon"
        path.write_text(json.dumps(index))
        code, output = self.run_check()
        self.assertEqual(code, 1, output)
        self.assertIn(f"::error::{path}: ", output)

    def test_explicit_manifests_do_not_discover_the_index(self):
        path, index = self.write_homekit()
        manifest = self.root / "firmware/homekit/manifest.json"
        path.write_text("invalid JSON")
        code, output = self.run_check(manifest)
        self.assertEqual(code, 0, output)
        self.assertNotIn("versions.json", output)
        self.rejects()  # the scan finds the broken index


if __name__ == "__main__":
    unittest.main()
