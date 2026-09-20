#!/usr/bin/env python3
"""Validate distribution manifests or explicit staged manifests before publishing.

No arguments scans both manifest.json and factory-manifest.json under firmware/.
ESP Web Tools builds retain the app hash and require hashes for every part of
a multipart image. A single merged image can use its build hash. Link OTA and
factory images require the pinned signer and embedded version. A factory build
may also list split parts for USB installs that keep the settings partition;
those must reassemble to the merged image byte for byte.
"""
import argparse
import contextlib
import hashlib
import io
import json
import pathlib
import re
import struct
import sys
import tempfile
from urllib.parse import urlsplit

try:
    import espsecure
    from esptool import FatalError
    from esptool.bin_image import ESP32S3FirmwareImage
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    sys.exit("Install validation tools: python -m pip install -r scripts/requirements-validation.txt")

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_KEY = ROOT / "scripts/keys/serin-link-release.pub"
WEB_BOARDS = {"m5atoms3-lite": "ESP32-S3", "nanoc6": "ESP32-C6"}
FLASH_SIZE = {"ESP32-S3": 8 * 1024 * 1024, "ESP32-C6": 4 * 1024 * 1024}
LINK_PARTITIONS = {
    "nvs": (1, 2, 0x9000, 0x6000, 0),
    "otadata": (1, 0, 0xf000, 0x2000, 0),
    "phy_init": (1, 1, 0x11000, 0x1000, 0),
    "ota_0": (0, 16, 0x20000, 0x400000, 0),
    "ota_1": (0, 17, 0x420000, 0x400000, 0),
}
# Split factory parts: offset -> the most flash the part may cover. nvs
# (0x9000-0xf000) and phy_init sit between them and must stay unwritten.
FACTORY_PART_LIMITS = {0: 0x8000, 0x8000: 0x1000, 0xf000: 0x2000, 0x20000: 0x400000}
FACTORY_CHANNEL_DIRS = {"link/factory-manifest.json": "stable",
                        "link/factory/beta/factory-manifest.json": "beta"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def positive_int(value, label):
    require(type(value) is int and value > 0, f"{label} must be a positive integer")


def digest_field(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            "sha256 must be 64 lowercase hexadecimal characters")


def asset_path(parent, value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./-]+", value),
            "path must be a relative local URL path")
    require(not value.startswith("/") and all(p not in ("", ".", "..") for p in value.split("/")),
            f"unsafe path {value!r}")
    path = (parent / value).resolve()
    require(path.is_relative_to(parent.resolve()), f"path escapes manifest directory: {value}")
    require(path.is_file(), f"path is missing or not a file: {value}")
    require(path.stat().st_size > 0, f"path is empty: {value}")
    return path


def check_hash(data, declared):
    digest_field(declared)
    require(hashlib.sha256(data).hexdigest() == declared, "sha256 does not match file contents")


def check_esp_image(data):
    """Parse an ESP32-S3 image and check its ordinary image checksums."""
    with contextlib.redirect_stdout(io.StringIO()):
        image = ESP32S3FirmwareImage(io.BytesIO(data))
    require(image.chip_id == 9, "image targets a chip other than ESP32-S3")
    require(image.segments and image.calculate_checksum() == image.checksum, "invalid ESP image checksum")
    require(image.append_digest and image.stored_digest == image.calc_digest, "invalid ESP image SHA-256")
    return image


def check_link_app(data, version):
    require(8192 <= len(data) <= 0x400000 and len(data) % 4096 == 0,
            "signature: app must fit a 4 MiB OTA slot and have a complete signature sector")
    sector = data[-4096:]
    require(sector[:2] == b"\xe7\x02" and sector[1216:] == b"\xff" * (4096 - 1216),
            "signature: expected a single RSA signature in block zero")
    pem = PUBLIC_KEY.read_bytes()
    public = serialization.load_pem_public_key(pem)
    require(isinstance(public, rsa.RSAPublicKey) and public.key_size == 3072,
            "signature: pinned key must be RSA-3072")
    with tempfile.TemporaryDirectory(prefix="serin-verify-") as tmp:
        digest = pathlib.Path(tmp) / "key-digest.bin"
        with PUBLIC_KEY.open("rb") as key, contextlib.redirect_stdout(io.StringIO()):
            espsecure.digest_sbv2_public_key(argparse.Namespace(keyfile=key, output=str(digest)))
        require(hashlib.sha256(sector[36:812]).digest() == digest.read_bytes(),
                "signature: embedded signing key differs from the production key")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            espsecure.verify_signature_v2(argparse.Namespace(
                keyfile=io.BytesIO(pem), datafile=io.BytesIO(data), hsm=False))
    except FatalError as error:
        raise ValueError(f"signature: {error}") from error
    image = check_esp_image(data[:-4096])
    signature_offset = ((image.data_length + 32 + 4095) // 4096) * 4096
    require(signature_offset == len(data) - 4096,
            "signature is not at the offset determined by the ESP image length")
    desc = image.segments[0].data[:256]
    require(image.segments[0].file_offs == 24 and len(desc) == 256
            and desc[:4] == b"\x32\x54\xcd\xab", "version: missing app descriptor")
    raw, terminator, _ = desc[16:48].partition(b"\0")
    require(raw and terminator, "version: descriptor version is empty or unterminated")
    require(raw.decode("ascii") == version, "version: embedded app version differs from manifest")


def check_factory(data, version):
    require(0x22000 <= len(data) <= 0x420000, "factory size does not fit the ota_0 layout")
    check_esp_image(data[:0x8000])
    table = data[0x8000:0x8c00]
    partitions = {}
    checksum_found = False
    for offset in range(0, len(table), 32):
        entry = table[offset:offset + 32]
        if entry[:2] == b"\xeb\xeb":
            require(entry[:16] == b"\xeb\xeb" + b"\xff" * 14
                    and entry[16:] == hashlib.md5(table[:offset]).digest(),
                    "partition table checksum is invalid")
            require(table[offset + 32:] == b"\xff" * (len(table) - offset - 32),
                    "partition table has data after its checksum")
            checksum_found = True
            break
        require(entry[:2] == b"\xaa\x50", "partition table entry or checksum is missing")
        _, typ, sub, start, size, label, flags = struct.unpack("<2sBBII16sI", entry)
        name = label.split(b"\0", 1)[0].decode("ascii")
        require(name not in partitions, f"duplicate partition {name}")
        partitions[name] = (typ, sub, start, size, flags)
    require(checksum_found and partitions == LINK_PARTITIONS,
            "partition layout differs from the supported Link layout (offsets, sizes, types or flags)")
    check_link_app(data[0x20000:], version)


def check_factory_parts(parts, parent, merged):
    """Split parts let a USB install skip nvs, so they must be the merged image
    and nothing else: same bytes, fixed offsets, 0xFF everywhere between."""
    require(isinstance(parts, list) and all(isinstance(p, dict) for p in parts),
            "parts must be an array of objects")
    offsets = [p.get("offset") for p in parts]
    require(all(type(o) is int for o in offsets) and sorted(offsets) == sorted(FACTORY_PART_LIMITS),
            "factory parts must sit at exactly the bootloader, partition table, otadata and ota_0 offsets")
    rebuilt = bytearray(b"\xff" * len(merged))
    files = set()
    for part in parts:
        path = asset_path(parent, part.get("path"))
        require(path not in files, "duplicate part path")
        files.add(path)
        data, offset = path.read_bytes(), part["offset"]
        try:
            check_hash(data, part.get("sha256"))
        except ValueError as error:
            raise ValueError(f"{part['path']}: {error}") from error
        require(len(data) <= FACTORY_PART_LIMITS[offset], f"{part['path']}: part overruns its flash region")
        require(merged[offset:offset + len(data)] == data, f"{part['path']}: part differs from the merged image")
        # A short otadata write would leave a stale boot selection pointing at
        # ota_1; blank otadata is what makes the bootloader pick the new ota_0.
        if offset == 0xf000:
            require(data == b"\xff" * 0x2000, f"{part['path']}: otadata part must be a full blank partition")
        rebuilt[offset:offset + len(data)] = data
    require(bytes(rebuilt) == merged, "parts do not reassemble to the merged factory image")
    return files


def check_web_build(build, parent):
    board, family = build.get("board"), build.get("chipFamily")
    require(isinstance(board, str) and board in WEB_BOARDS, "unknown controller board")
    require(family == WEB_BOARDS[board], "chipFamily does not match board")
    require(not any(k in build for k in ("path", "size", "enc_size")), "mixed manifest formats")
    parts = build.get("parts")
    require(isinstance(parts, list) and parts, "parts must be a nonempty array")
    files, ranges = [], []
    for part in parts:
        require(isinstance(part, dict), "part must be an object")
        path = asset_path(parent, part.get("path"))
        offset = part.get("offset")
        require(type(offset) is int and offset >= 0 and offset % 4096 == 0,
                "part offset must be a nonnegative flash-sector-aligned integer")
        end = offset + ((path.stat().st_size + 4095) // 4096) * 4096
        require(end <= FLASH_SIZE[family], "part exceeds board flash size")
        require(path not in files, "duplicate part path")
        files.append(path)
        ranges.append((offset, end))
    ranges.sort()
    require(all(right[0] >= left[1] for left, right in zip(ranges, ranges[1:])), "flash parts overlap")
    targets = [p for p in files if p.name == "firmware.bin"]
    target = files[0] if len(files) == 1 else targets[0] if len(targets) == 1 else None
    require(target is not None, "cannot identify the part covered by sha256")
    for part, path in zip(parts, files):
        if len(parts) > 1 or "sha256" in part:
            try:
                check_hash(path.read_bytes(), part.get("sha256"))
            except ValueError as error:
                raise ValueError(f"{part['path']}: {error}") from error
    check_hash(target.read_bytes(), build.get("sha256"))
    return set(files)


def check_link_build(build, parent, version, kind):
    board = build.get("board")
    require(isinstance(board, str) and board in ({"viewe15", "viewe21"} if kind == "factory" else {"link15", "link21"}),
            "unknown Link board for this manifest format")
    require("chipFamily" not in build and (kind == "factory" or "parts" not in build),
            "mixed manifest formats")
    require("enc_size" not in build, "the encrypted Link format is retired; releases must use signed plaintext")
    path = asset_path(parent, build.get("path"))
    positive_int(build.get("size"), "size")
    digest_field(build.get("sha256"))
    data = path.read_bytes()
    require(len(data) == build["size"], "size differs from file size")
    check_hash(data, build["sha256"])
    files = {path}
    if kind == "factory":
        check_factory(data, version)
        if "parts" in build:
            parts = check_factory_parts(build["parts"], parent, data)
            require(path not in parts, "duplicate part path")
            files |= parts
    else:
        check_link_app(data, version)
    print(f"  ok  {board}: size, sha256, signature and embedded version"
          + (", split parts" if len(files) > 1 else ""))
    return files


def validate_manifest(path, allow_dirty=False):
    manifest = read_json(path)
    require(isinstance(manifest, dict), "manifest must be an object")
    require(isinstance(manifest.get("name"), str) and manifest["name"].strip(), "name must be a nonempty string")
    version = manifest.get("version")
    require(isinstance(version, str) and len(version) <= 31
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z]+\.[0-9]+)?", version), "invalid version")
    channel = manifest.get("channel", "stable")
    require(channel in ("stable", "beta"), "channel must be stable or beta")
    require((channel == "beta") == ("-" in version), "channel does not match release version")
    if "new_install_prompt_erase" in manifest:
        require(type(manifest["new_install_prompt_erase"]) is bool, "new_install_prompt_erase must be a boolean")
    if "release_url" in manifest:
        value = manifest["release_url"]
        require(isinstance(value, str), "release_url must be an HTTPS URL")
        url = urlsplit(value)
        require(url.scheme == "https" and url.hostname and not url.username and not url.password,
                "release_url must be an HTTPS URL without credentials")
    builds = manifest.get("builds")
    require(isinstance(builds, list) and builds and all(isinstance(b, dict) for b in builds),
            "builds must be a nonempty array of objects")
    require(path.name in ("manifest.json", "factory-manifest.json"), "unsupported manifest filename")
    if path.name == "factory-manifest.json":
        kind = "factory"
        require(type(manifest.get("dirty")) is bool, "factory dirty provenance must be a boolean")
        require(allow_dirty or not manifest["dirty"], "dirty factory build cannot be published")
        if manifest["dirty"]:
            print("::warning::dirty factory build: local inspection only, not approved for publication")
    elif any("parts" in build for build in builds):
        kind = "web"
    else:
        kind = "link"
    # Distribution paths identify the intended consumer. Do not let changing
    # a Link manifest to a controller shape silently bypass Link verification.
    try:
        relative = path.resolve().relative_to((ROOT / "firmware").resolve())
        product = relative.parts[0]
    except ValueError:
        product = None  # Explicit staged manifests may be outside the checkout.
    if product == "link":
        require(kind != "web", "controller format is invalid in the Link distribution")
        if kind == "factory":
            require(relative.as_posix() in FACTORY_CHANNEL_DIRS, "unknown Link factory directory")
            expected_channel = FACTORY_CHANNEL_DIRS[relative.as_posix()]
        else:
            require(relative.as_posix() in ("link/ota/stable/manifest.json", "link/ota/beta/manifest.json"),
                    "unknown Link OTA channel directory")
            expected_channel = relative.parts[2]
        require(channel == expected_channel, "manifest channel does not match the channel directory")
    elif product in ("esphome", "homekit", "matter"):
        require(kind == "web", "Link format is invalid in a controller distribution")
    referenced, boards = set(), set()
    for build in builds:
        board = build.get("board")
        require(isinstance(board, str), "board must be a string")
        require(board not in boards, f"duplicate board {board}")
        boards.add(board)
        if kind == "web":
            referenced.update(check_web_build(build, path.parent))
        else:
            files = check_link_build(build, path.parent, version, kind)
            require(not referenced.intersection(files), "duplicate Link artifact path")
            referenced.update(files)
    return referenced


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="*", type=pathlib.Path, help="explicit staged manifests; default: scan firmware/")
    parser.add_argument("--allow-dirty", action="store_true", help="inspect dirty factory builds locally; never use for publication")
    args = parser.parse_args()
    manifests = args.manifests or sorted(set(ROOT.glob("firmware/**/manifest.json")) |
                                        set(ROOT.glob("firmware/**/factory-manifest.json")))
    if not manifests:
        print("::error::no manifests found under firmware/")
        return 1
    errors, referenced = 0, set()
    for path in manifests:
        print(f"\n{path}")
        try:
            referenced.update(validate_manifest(path, args.allow_dirty))
        except (OSError, ValueError, TypeError, KeyError, struct.error, FatalError) as error:
            print(f"::error::{path}: {error}")
            errors += 1
    stray = 0
    if not args.manifests and not errors:
        link = (ROOT / "firmware/link").resolve()
        for orphan in sorted(ROOT.glob("firmware/**/*.bin")):
            if orphan.resolve() in referenced:
                continue
            # Link files are copied in by hand, not rewritten by a workflow, so
            # a leftover image is a skipped release step (e.g. a renamed
            # factory image) that would otherwise stay downloadable.
            if orphan.resolve().is_relative_to(link):
                print(f"::error::{orphan}: Link file not referenced by any manifest")
                stray += 1
            else:
                print(f"::warning::{orphan}: not referenced by any manifest")
    if errors:
        print(f"FAILED: {errors} manifest(s) invalid")
        return 1
    if stray:
        print(f"FAILED: {stray} unreferenced Link file(s); remove them or reference them from a manifest")
        return 1
    print(f"OK: {len(manifests)} manifests validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
