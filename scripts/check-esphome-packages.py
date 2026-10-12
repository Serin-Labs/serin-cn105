"""Verify local and dashboard imports use the selected checkout's packages.

Run with the release Python environment: python scripts/check-esphome-packages.py
Only Git transport is simulated. ESPHome loads and merges the actual configs.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from esphome import yaml_util
from esphome.components import packages
from esphome.core import CORE


ROOT = Path(__file__).resolve().parents[1]
BOARDS = {"esp32c6": "esp32-c6-devkitm-1", "esp32s3": "esp32-s3-devkitc-1"}
LINK_DEVICE = {"id": "link1", "name": "Serin Link 1"}


class PackageRevisionTests(unittest.TestCase):
    def setUp(self):
        CORE.reset()

    def assertLinkIsItsOwnDevice(self, merged):
        # ESPHome compiles sub-devices in from esphome: devices:, and
        # serin_link cannot add one when a Link pairs. Without the declaration
        # Home Assistant lists no device for the Link and its entities sit
        # flat on the controller.
        self.assertEqual(merged["esphome"].get("devices"), [LINK_DEVICE])
        link = merged["serin_link"]
        # One device per slot, in slot order: the count and the list agree.
        self.assertEqual(link.get("link_devices"), [LINK_DEVICE["id"]])
        self.assertEqual(merged["substitutions"]["max_links"], "1")
        # A bare links: puts Temperature and Humidity on that device. The flat
        # pair would be the same two readings on the controller as well.
        self.assertIn("links", link["link_sensor"])
        self.assertNotIn("temperature", link["link_sensor"])
        self.assertNotIn("humidity", link["link_sensor"])

    def test_local_build_never_fetches_shared_packages_from_main(self):
        for board, hardware in BOARDS.items():
            with self.subTest(board=board):
                CORE.config_path = ROOT / f"esphome/serin_{board}.yaml"
                raw = yaml_util.load_yaml(CORE.config_path)
                with patch("esphome.git.clone_or_update", side_effect=AssertionError(
                    "Local builds must use packages from the checked-out revision"
                )):
                    merged = packages.merge_packages(packages.do_packages_pass(raw))
                self.assertEqual(merged["esp32"]["board"], hardware)
                self.assertTrue(merged["serin_link"]["link_ota_credentials"])
                # The prebuilt web-flasher firmware ships as a Bluetooth proxy.
                self.assertIn("esp32_ble_tracker", merged)
                self.assertTrue(merged["bluetooth_proxy"]["active"])
                self.assertLinkIsItsOwnDevice(merged)

    def test_dashboard_import_resolves_includes_inside_the_selected_revision(self):
        for board in BOARDS:
            with self.subTest(board=board):
                CORE.config_path = ROOT / "dashboard-device.yaml"
                remote = {
                    "packages": {
                        "device": {
                            "url": "https://github.com/Serin-Labs/serin-cn105.git",
                            "ref": "selected-release-revision",
                            "files": [f"esphome/serin_{board}.yaml"],
                        }
                    }
                }
                with patch("esphome.git.clone_or_update", return_value=(ROOT, None)) as fetch:
                    merged = packages.merge_packages(packages.do_packages_pass(remote))
                self.assertEqual(fetch.call_count, 1, "Nested packages must not fetch a different revision")
                self.assertEqual(fetch.call_args.kwargs["ref"], "selected-release-revision")
                self.assertTrue(merged["serin_link"]["link_ota_credentials"])
                self.assertEqual(merged["wifi"]["ap"]["password"], "serinlabs")
                self.assertLinkIsItsOwnDevice(merged)


if __name__ == "__main__":
    unittest.main()
