#!/usr/bin/env python3
"""Write firmware/homekit/versions.json and the app images it points at.

The device web UI reads the index to list every archived release. Release CI
and the one-off backfill both call `add`, which is idempotent: running it again
for the same version and images leaves every file untouched.

Archive layout, relative to the index's directory:
    archive/<version>/<board>/firmware.bin

`cmp_versions` is a port of parseVer/cmpVer in the firmware web UI
(web/index.html, tested by test/version_compare/test.js) so the index and the
menu always agree on what "newest" means.
"""
import argparse
import functools
import hashlib
import json
from pathlib import Path
import re
import sys

INDEX_NAME = "Mitsubishi HomeKit Controller"

# JS String.prototype.trim whitespace, which parseInt skips before the digits.
_JS_SPACE = "\t\n\v\f\r    -     　﻿"
_LEADING_INT = re.compile(rf"[{_JS_SPACE}]*([+-]?[0-9]+)")
_DIRTY = re.compile(r"-dirty\Z")
_GIT_TAIL = re.compile(r"([^\n\r\u2028\u2029]*)-[0-9]+-g[0-9a-f]{7,}\Z")
_NUMERIC = re.compile(r"[0-9]+\Z")
# A version or board becomes a path component, so it must not escape the archive.
_SAFE_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*\Z")


def _parse_int(text):
    """JS parseInt(text, 10) || 0: leading digits count, anything else is 0."""
    m = _LEADING_INT.match(text)
    return int(m.group(1)) if m else 0


def _parse_ver(text):
    v = text or ""
    v = v[1:] if v.startswith("v") else v
    v = _DIRTY.sub("", v, count=1)
    m = _GIT_TAIL.match(v)
    if m:
        v = m.group(1)
    i = v.find("-")
    core = [_parse_int(x) for x in (v if i < 0 else v[:i]).split(".")]
    pre = None
    if i >= 0:
        pre = [int(x) if _NUMERIC.match(x) else x for x in v[i + 1:].split(".")]
    return core, pre


def _utf16(text):
    # JS compares strings by UTF-16 code unit, Python by code point.
    return text.encode("utf-16-be", "surrogatepass")


def cmp_versions(a, b):
    """Return -1, 0 or 1 exactly as the UI's cmpVer does."""
    core_a, pre_a = _parse_ver(a)
    core_b, pre_b = _parse_ver(b)
    for i in range(max(len(core_a), len(core_b))):
        x = core_a[i] if i < len(core_a) else 0
        y = core_b[i] if i < len(core_b) else 0
        if x != y:
            return -1 if x < y else 1
    # A prerelease sorts below the same core without one.
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1
    for i in range(max(len(pre_a), len(pre_b))):
        if i >= len(pre_a):
            return -1
        if i >= len(pre_b):
            return 1
        p, q = pre_a[i], pre_b[i]
        p_num, q_num = isinstance(p, int), isinstance(q, int)
        if p_num != q_num:
            return -1 if p_num else 1
        if p != q:
            if not p_num:
                p, q = _utf16(p), _utf16(q)
            return -1 if p < q else 1
    return 0


def archive_path(version, board):
    return f"archive/{version}/{board}/firmware.bin"


def _check_name(kind, value):
    if not _SAFE_NAME.match(value):
        raise ValueError(f"unsafe {kind} for an archive path: {value!r}")


def _newest_first(a, b):
    # Versions that compare equal (0.2 and 0.2.0) fall back to text so the
    # file does not depend on the order entries were added.
    return cmp_versions(b["version"], a["version"]) or (b["version"] > a["version"]) - (b["version"] < a["version"])


def upsert(index_path, version, date, release_url, images):
    """Archive `images` ({board: bytes}) and record them under `version`.

    Returns True when the index file's content changed. An existing entry keeps
    its date and any boards not named in `images`.
    """
    index_path = Path(index_path)
    _check_name("version", version)
    for board in images:
        _check_name("board", board)

    if index_path.exists():
        before = index_path.read_bytes()
        index = json.loads(before)
    else:
        before = None
        index = {"name": INDEX_NAME, "versions": []}
    versions = index.setdefault("versions", [])

    entry = next((e for e in versions if e.get("version") == version), None)
    builds = dict(entry.get("builds", {})) if entry else {}
    date = entry.get("date", date) if entry else date

    for board, data in images.items():
        target = index_path.parent / archive_path(version, board)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        builds[board] = {"path": archive_path(version, board), "sha256": hashlib.sha256(data).hexdigest()}

    updated = {"version": version, "date": date, "release_url": release_url,
               "builds": {board: builds[board] for board in sorted(builds)}}
    if entry:
        versions[versions.index(entry)] = updated
    else:
        versions.append(updated)
    versions.sort(key=functools.cmp_to_key(_newest_first))

    after = (json.dumps(index, indent=2) + "\n").encode("utf-8")
    if after == before:
        return False
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(after)
    return True


def _build_arg(text):
    board, sep, file = text.partition("=")
    if not sep or not board or not file:
        raise argparse.ArgumentTypeError(f"expected BOARD=FILE, got {text!r}")
    return board, Path(file)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="archive images and record a version in the index")
    add.add_argument("--index", required=True, type=Path)
    add.add_argument("--version", required=True)
    add.add_argument("--date", required=True, help="YYYY-MM-DD")
    add.add_argument("--release-url", required=True)
    add.add_argument("--build", required=True, action="append", type=_build_arg, metavar="BOARD=FILE")
    args = parser.parse_args(argv)

    try:
        images = {board: file.read_bytes() for board, file in args.build}
        changed = upsert(args.index, args.version, args.date, args.release_url, images)
    except (OSError, ValueError) as err:
        sys.exit(f"homekit_index: {err}")
    print(f"{args.index}: {'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
