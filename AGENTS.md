# serin-cn105

A distribution repo, not an application. Four firmware products are published
here from three different upstream repos, and two consumers read this repo's
`main` branch directly over `raw.githubusercontent.com`:

- the web installer at `serin-labs.github.io` (`assets/js/flash-console.js`)
- the Serin Link dial's own OTA updater

There is no build to run and nothing to serve. A bad merge to `main` is live to
users immediately, with no deploy step in between. The only gate is
`scripts/validate-manifests.py`; run it, and its tests, before every push:

```bash
python -m pip install -r scripts/requirements-validation.txt
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/validate-manifests.py
```

`docs/release-validation.md` is the full contract. Serin Link's CI checks out
`scripts/` at a pinned commit of this repo, so a change to the validator's
command line or checks needs a matching pin bump in `serin-link`'s
`.github/workflows/ci.yml`. Land such commits on `main` by fast-forward: a
squash or rebase changes the SHA that pin names.

## What is generated and what is hand-edited

| Path | Owner | Never hand-edit |
|------|-------|-----------------|
| `firmware/esphome/` | `.github/workflows/esphome-firmware.yml` in this repo | yes |
| `firmware/homekit/`, `firmware/homekit/beta/` | `firmware-release.yml` in `akifbayram/mitsubishi-cn105-homekit` | yes |
| `firmware/matter/` | the private Matter repo's release workflow | yes |
| `firmware/link/ota/stable/`, `firmware/link/ota/beta/` | `tools/publish_fw.py --distribution` in `Serin-Labs/serin-link`, run by hand; it stages files and never commits or pushes | yes |
| `firmware/link/factory-manifest.json` and its images | copied by hand from `serin-link`'s `publish_fw.py --factory` output | yes |
| `firmware/link/manifest.json`, `firmware/link/beta/`, `firmware/link/link15/`, `firmware/link/link21/` | archived encrypted feeds, frozen; `scripts/legacy-link-artifacts.json` pins their bytes | never change |
| `esphome/` | hand-edited | — |
| `docs/`, `README.md` | hand-edited | — |

ESPHome, HomeKit and Matter publish here using the Serin Firmware Publisher
GitHub App; its pushes trigger this repo's validation workflows. For credential
setup, rotation, or ruleset bypass changes, read the Publisher authentication
section of `docs/release-validation.md`. Link has no release workflow: stage
its files with the publisher, validate them, and submit a PR for review.

## The manifest contract

Every `firmware/*/manifest.json` is the source of truth for its product, and
`README.md` is not. Consumers fetch the manifest and resolve `parts[].path`
relative to the manifest's own URL, so a manifest can move directories without
rewriting any path inside it. Keep paths relative.

Two families of shape exist:

**ESP Web Tools shape** (`esphome`, `homekit`, `matter`) — `builds[]` keyed by
`chipFamily`, each with `parts[]` of `{path, offset, sha256}`. Multipart builds
require every part hash. The build-level `sha256` retains the app hash for OTA;
a single merged image can use that hash alone. The installer picks a
build by matching `chipFamily` against the chip it detected over serial.

**Serin Link shapes** — one `path` per board, plus `size` and `sha256`:

- *Plaintext OTA* (`firmware/link/ota/<channel>/manifest.json`, boards
  `link15`/`link21`): signed app images. `sha256` and `size` describe the file
  on disk, the first signature block must carry the pinned key in
  `scripts/keys/serin-link-release.pub`, and the image's embedded version must
  equal the manifest's. `channel` must match the directory.
- *Factory* (`firmware/link/factory-manifest.json`, boards `viewe15`/`viewe21`):
  merged images flashed at `0x0` by the web installer. The validator also
  checks the bootloader, the exact partition layout, the signed app at
  `0x20000`, and `dirty: false`.
- *Archived encrypted OTA* (the frozen paths above): these add `enc_size`, and
  `sha256` is the hash of the *decrypted* image, so it never matches the file.
  The validator only checks them against the archive index; their plaintext is
  unverifiable here.

Installed encrypted updaters poll `firmware/link/manifest.json` and
`firmware/link/beta/manifest.json`; current firmware polls the `ota/` feeds.
The formats are not interchangeable, so a plaintext image must never land at
an encrypted path, and the reverse also holds.

Pairing codes are never carried in a manifest. HomeKit and Matter both derive
theirs from the device MAC, and the installer recomputes them client-side.

## Traps

- **Any push touching `esphome/**` rebuilds and republishes firmware.** The
  workflow compiles both boards and commits new binaries to
  `firmware/esphome/` on `main`. There is no such thing as a cosmetic edit to
  those configs.
- **`esphome/common/*.yaml` is vendored downstream.** The site's
  `sync-esphome-fragments.yml` copies the whole directory into its own
  `esphome/fragments/`, and its YAML generator maps *specific filenames*
  (`generate-yaml.html`). Renaming or splitting a fragment silently drops
  content from every generated config, and the site's tests will not catch it.
  Adding a new optional fragment is safe; restructuring existing ones is a
  coordinated two-repo change.
- **ESPHome is pinned in `requirements.txt`.** The pin governs the prebuilt
  binaries only. Home Assistant users adopting via `dashboard_import` compile
  with their own ESPHome, so `min_version` in the board configs is the contract
  that matters for them. Keep both, and keep them consistent.
- **An unreferenced `.bin` under `firmware/link/` fails validation.** Link
  files arrive by hand, so a leftover one (for example the `serin_dial_*`
  factory images once `serin_link_*` replaces them) is a skipped release step.
  Remove it in the same commit. Elsewhere under `firmware/`, orphans only warn.
- **Never regenerate `scripts/legacy-link-artifacts.json` to make a changed
  archived Link file pass.** The index exists to detect exactly that change.
- **`.ota-stage-*/` at the root is `publish_fw.py --distribution` scratch.**
  It is gitignored; delete one left behind by an interrupted run.
- **Binaries accumulate in git history.** The pack is checked on every
  `firmware/**` push and warns past 250 MB; see the README's Building section
  for the intended migration when it trips.
