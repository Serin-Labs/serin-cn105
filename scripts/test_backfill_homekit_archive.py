#!/usr/bin/env python3
"""Tests for the archive backfill's image identity filter."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location("backfill", Path(__file__).with_name("backfill-homekit-archive.py"))
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

CHIP_C6, CHIP_S3 = 13, 9


def make_image(chip=CHIP_C6, project=b"mitsubishi-cn105-homekit", first=0xE9, magic=0xABCD5432):
    """A 288-byte header: image header (24) + segment header (8) + esp_app_desc_t."""
    data = bytearray(288)
    data[0] = first
    struct.pack_into("<H", data, 12, chip)
    struct.pack_into("<I", data, 32, magic)
    data[80:80 + len(project)] = project
    return bytes(data)


class AcceptsTests(unittest.TestCase):
    def test_accepts_a_c6_image_for_nanoc6(self):
        ok, reason = backfill.accepts("nanoc6", make_image(CHIP_C6))
        self.assertTrue(ok, reason)

    def test_accepts_an_s3_image_for_m5atoms3_lite(self):
        ok, reason = backfill.accepts("m5atoms3-lite", make_image(CHIP_S3))
        self.assertTrue(ok, reason)

    def test_project_name_ends_at_the_first_nul(self):
        junk = b"mitsubishi-cn105-homekit\0trailing bytes"
        ok, reason = backfill.accepts("nanoc6", make_image(project=junk))
        self.assertTrue(ok, reason)

    def test_rejects_the_arduino_project(self):
        ok, reason = backfill.accepts("nanoc6", make_image(project=b"arduino-lib-builder"))
        self.assertFalse(ok)
        self.assertIn("arduino-lib-builder", reason)

    def test_rejects_a_project_name_that_only_starts_with_ours(self):
        ok, reason = backfill.accepts("nanoc6", make_image(project=b"mitsubishi-cn105-homekit-dial"))
        self.assertFalse(ok)
        self.assertIn("mitsubishi-cn105-homekit-dial", reason)

    def test_rejects_the_wrong_chip_for_the_board(self):
        ok, reason = backfill.accepts("m5atoms3-lite", make_image(CHIP_C6))
        self.assertFalse(ok)
        self.assertIn("chip", reason)
        ok, reason = backfill.accepts("nanoc6", make_image(CHIP_S3))
        self.assertFalse(ok)
        self.assertIn("chip", reason)

    def test_rejects_boards_it_does_not_archive(self):
        ok, reason = backfill.accepts("esp32-devkit", make_image(CHIP_C6))
        self.assertFalse(ok)
        self.assertIn("esp32-devkit", reason)

    def test_rejects_bad_magic_short_data_and_missing_app_desc(self):
        good = make_image()
        cases = {
            "empty": b"",
            "not an image": b"\x00" * 288,
            "wrong first byte": make_image(first=0x7F),
            "no app desc magic": make_image(magic=0),
            "truncated inside the project name": good[:111],
            "truncated before the app desc": good[:31],
        }
        for label, data in cases.items():
            with self.subTest(label):
                ok, reason = backfill.accepts("nanoc6", data)
                self.assertFalse(ok)
                self.assertTrue(reason)

    def test_the_shortest_complete_header_is_enough(self):
        ok, reason = backfill.accepts("nanoc6", make_image()[:112])
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
