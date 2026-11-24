#!/usr/bin/env python3
"""Archive every published HomeKit release into firmware/homekit/versions.json.

One-off backfill: it reads the GitHub releases of the firmware repo, downloads
each `firmware-<board>.bin`, keeps only the images this project built, and
records them with homekit_index.upsert. Rerunning it is safe; images that are
already archived are rewritten with identical bytes and the index stays put.

An image is kept only if it passes the same identity check as the device's OTA
guard (main/ota_guard.h in the firmware repo): the older releases also carry
Arduino-era builds and boards that are not archived, and those must not be
offered as installable versions.

Needs an authenticated `gh`.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "akifbayram/mitsubishi-cn105-homekit"
DEFAULT_INDEX = ROOT / "firmware" / "homekit" / "versions.json"

# Archived board -> ESP image header chip id (ESP32-C6 and ESP32-S3).
BOARD_CHIPS = {"nanoc6": 13, "m5atoms3-lite": 9}
IMAGE_MAGIC = 0xE9
# esp_app_desc_t follows the 24-byte image header and the 8-byte first segment header.
APP_DESC_MAGIC = 0xABCD5432
PROJECT_NAME = b"mitsubishi-cn105-homekit"
CHIP_ID_OFFSET, APP_DESC_OFFSET, PROJECT_OFFSET, PROJECT_END = 12, 32, 80, 112

spec = importlib.util.spec_from_file_location("homekit_index", Path(__file__).with_name("homekit_index.py"))
homekit_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(homekit_index)


def accepts(board, data):
    """Return (True, "ok") when `data` is this project's image for `board`, else (False, reason)."""
    chip = BOARD_CHIPS.get(board)
    if chip is None:
        return False, f"board {board} is not archived"
    if len(data) < PROJECT_END:
        return False, f"too short ({len(data)} bytes, need {PROJECT_END})"
    if data[0] != IMAGE_MAGIC:
        return False, f"not an app image (first byte 0x{data[0]:02x})"

    problems = []
    (found_chip,) = struct.unpack_from("<H", data, CHIP_ID_OFFSET)
    if found_chip != chip:
        problems.append(f"chip id {found_chip}, want {chip}")
    (magic,) = struct.unpack_from("<I", data, APP_DESC_OFFSET)
    if magic != APP_DESC_MAGIC:
        problems.append(f"no app description (magic 0x{magic:08x})")
    else:
        project = data[PROJECT_OFFSET:PROJECT_END].split(b"\0", 1)[0]
        if project != PROJECT_NAME:
            problems.append("project " + project.decode("ascii", "backslashreplace"))
    return (False, ", ".join(problems)) if problems else (True, "ok")


def run_gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True)
    if done.returncode:
        sys.exit(f"backfill: gh {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def list_releases(repo):
    """Every release of `repo`. `--jq '.[]'` makes the pages one object each, back to back."""
    text = run_gh("api", "--paginate", f"repos/{repo}/releases", "--jq", ".[]").decode("utf-8")
    decoder, releases, pos = json.JSONDecoder(), [], 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return releases
        release, pos = decoder.raw_decode(text, pos)
        releases.append(release)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo that publishes the releases")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX,
                        help="index to write; the archive goes next to it (default: firmware/homekit/versions.json)")
    args = parser.parse_args(argv)

    archived = 0
    for release in list_releases(args.repo):
        if release.get("draft"):
            continue
        tag = release["tag_name"]
        assets = {asset["name"] for asset in release.get("assets", [])}
        images, skipped = {}, []
        for board in BOARD_CHIPS:
            name = f"firmware-{board}.bin"
            if name not in assets:
                skipped.append(f"{board}: no {name} asset")
                continue
            data = run_gh("release", "download", tag, "-R", args.repo, "-p", name, "-O", "-")
            ok, reason = accepts(board, data)
            if ok:
                images[board] = data
            else:
                skipped.append(f"{board}: {reason}")
        if not images:
            print(f"skip {tag}: {'; '.join(skipped)}")
            continue
        try:
            homekit_index.upsert(args.index, tag.lstrip("v"), release["published_at"][:10],
                                 release["html_url"], images)
        except ValueError as err:
            print(f"skip {tag}: {err}")
            continue
        archived += 1
        note = f" (skipped {'; '.join(skipped)})" if skipped else ""
        print(f"archive {tag}: {', '.join(images)}{note}")
    print(f"{args.index}: {archived} versions archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
