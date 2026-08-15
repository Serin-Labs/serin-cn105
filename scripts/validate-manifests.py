#!/usr/bin/env python3
"""Validate every firmware manifest in this repo against the binaries beside it.

This repo is a CDN with a git front-end: the web installer and the Serin Link
updater read manifests straight from `main`, so a manifest that names a file
that is not there is a broken install for every user the moment it lands. Three
of the four products are published by workflows in *other* repos, which is
exactly why the check lives here rather than in any one of them.

Two manifest shapes exist; see CLAUDE.md for the full contract.

  ESP Web Tools  builds[] of {chipFamily, sha256, parts[{path, offset}]}.
                 sha256 covers the firmware.bin part alone, not the whole
                 flash image, so that is the only part worth hashing.

  Serin Link     builds[] of {board, path, size, enc_size, sha256}. Only
                 ciphertext is hosted here and sha256 is over the *decrypted*
                 image, so it cannot be checked from this repo at all. The
                 on-disk size is enc_size, not size, and that can be.
"""

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED_KEYS = ("name", "version")

errors = []


def err(message):
    errors.append(message)
    print(f"::error::{message}")


def warn(message):
    print(f"::warning::{message}")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_target(build):
    """The part a build's sha256 is taken over.

    Multi-part builds hash firmware.bin; the merged single-part ESPHome images
    hash the one part they have.
    """
    parts = build.get("parts", [])
    firmware = [p for p in parts if p["path"].endswith("firmware.bin")]
    if firmware:
        return firmware[0]["path"]
    return parts[0]["path"] if len(parts) == 1 else None


def check_link(manifest, manifest_dir, rel):
    for build in manifest.get("builds", []):
        board = build.get("board", "?")
        path = manifest_dir / build["path"]
        if not path.exists():
            err(f"{rel}: {board}: {build['path']} is missing")
            continue
        actual = path.stat().st_size
        expected = build.get("enc_size")
        if expected is None:
            err(f"{rel}: {board}: no enc_size")
        elif actual != expected:
            err(f"{rel}: {board}: {build['path']} is {actual} B, enc_size says {expected}")
        else:
            print(f"  ok  {board}: {actual} B matches enc_size (sha256 is over plaintext, unverifiable here)")


def check_web_tools(manifest, manifest_dir, rel):
    for build in manifest.get("builds", []):
        board = build.get("board") or build.get("chipFamily", "?")
        missing = [p["path"] for p in build.get("parts", []) if not (manifest_dir / p["path"]).exists()]
        for path in missing:
            err(f"{rel}: {board}: {path} is missing")

        declared = build.get("sha256")
        target = hash_target(build)
        if declared is None:
            err(f"{rel}: {board}: no sha256")
        elif target is None:
            err(f"{rel}: {board}: cannot tell which part sha256 covers")
        elif target not in missing:
            actual = sha256(manifest_dir / target)
            if actual != declared:
                err(f"{rel}: {board}: {target} hashes to {actual}, manifest says {declared}")
            else:
                print(f"  ok  {board}: {target} matches sha256")


def main():
    manifests = sorted(ROOT.glob("firmware/**/manifest.json"))
    if not manifests:
        err("no manifests found under firmware/")
        return 1

    for manifest_path in manifests:
        rel = manifest_path.relative_to(ROOT)
        manifest_dir = manifest_path.parent
        print(f"\n{rel}")

        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as exc:
            err(f"{rel}: invalid JSON: {exc}")
            continue

        for key in REQUIRED_KEYS:
            if not manifest.get(key):
                err(f"{rel}: missing '{key}'")
        if not manifest.get("builds"):
            err(f"{rel}: no builds")
            continue

        if "link" in rel.parts:
            check_link(manifest, manifest_dir, rel)
            referenced = {(manifest_dir / b["path"]).resolve() for b in manifest["builds"]}
        else:
            check_web_tools(manifest, manifest_dir, rel)
            referenced = {
                (manifest_dir / p["path"]).resolve()
                for b in manifest["builds"]
                for p in b.get("parts", [])
            }

        # A binary no manifest names is dead weight at best and a stale build
        # someone is about to flash by hand at worst. Warn rather than fail:
        # nested channels legitimately own their own files.
        nested = {m.parent for m in manifests if m != manifest_path and manifest_dir in m.parents}
        for orphan in sorted(manifest_dir.rglob("*.bin")):
            if orphan.resolve() in referenced:
                continue
            if any(parent in orphan.parents for parent in nested):
                continue
            warn(f"{rel}: {orphan.relative_to(ROOT)} is not referenced by any build")

    print()
    if errors:
        print(f"FAILED: {len(errors)} problem(s)")
        return 1
    print(f"OK: {len(manifests)} manifests validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
