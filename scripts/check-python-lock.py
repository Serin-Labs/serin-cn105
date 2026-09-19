"""Check a clean build environment against its exact dependency lock."""

import argparse
from importlib.metadata import distributions
from pathlib import Path
import re


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    args = parser.parse_args()
    expected = {}
    for line in args.lock.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if not match:
            parser.error(f"Expected an exact package pin: {line}")
        name, version = match.groups()
        expected[normalize(name)] = version

    actual = {normalize(d.metadata["Name"]): d.version for d in distributions()}
    errors = [f"{name}: expected {version}, installed {actual.get(name, 'missing')}"
              for name, version in expected.items() if actual.get(name) != version]
    # ESPHome's lock omits the installer itself. The IDF lock includes pip
    # because ESPHome explicitly upgrades it when it creates that environment.
    errors.extend(f"{name}: installed but not locked"
                  for name in sorted(actual.keys() - expected.keys() - {"pip"}))
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print(f"{args.lock.name}: all {len(expected)} package versions match")


if __name__ == "__main__":
    main()
