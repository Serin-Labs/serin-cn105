# serin-cn105

A distribution repo, not an application. Four firmware products are published
here from three different upstream repos, and two consumers read this repo's
`main` branch directly over `raw.githubusercontent.com`:

- the web installer at `serin-labs.github.io` (`assets/js/flash-console.js`)
- the Serin Link dial's own OTA updater

There is no build to run and nothing to serve. A bad merge to `main` is live to
users immediately, with no deploy step in between.

## What is generated and what is hand-edited

| Path | Owner | Never hand-edit |
|------|-------|-----------------|
| `firmware/esphome/` | `.github/workflows/esphome-firmware.yml` in this repo | yes |
| `firmware/homekit/`, `firmware/homekit/beta/` | `firmware-release.yml` in `akifbayram/mitsubishi-cn105-homekit` | yes |
| `firmware/matter/` | the private Matter repo's release workflow | yes |
| `firmware/link/` | the `Serin-Labs/serin-link` release workflow | yes |
| `esphome/` | hand-edited | — |
| `docs/`, `README.md` | hand-edited | — |

The external workflows push here with the `SERIN_CN105_PAT` fine-grained token.
Because those pushes use a PAT rather than the default `GITHUB_TOKEN`, they
*do* trigger this repo's workflows — which is what makes `validate-manifests`
meaningful for the products this repo does not build itself.

## The manifest contract

Every `firmware/*/manifest.json` is the source of truth for its product, and
`README.md` is not. Consumers fetch the manifest and resolve `parts[].path`
relative to the manifest's own URL, so a manifest can move directories without
rewriting any path inside it. Keep paths relative.

Two shapes exist:

**ESP Web Tools shape** (`esphome`, `homekit`, `matter`) — `builds[]` keyed by
`chipFamily`, each with `parts[]` of `{path, offset}`. `sha256` covers the
`firmware.bin` part only, not the whole flash image. The installer picks a
build by matching `chipFamily` against the chip it detected over serial.

**Serin Link shape** — one `path` per board, plus `size`, `enc_size` and
`sha256`. Only ciphertext is hosted here: `sha256` is the hash of the
*decrypted* image, so it will never match the file on disk, and `enc_size` —
not `size` — is the on-disk byte count. `scripts/validate-manifests.py`
therefore checks size for Link and hash for everything else.

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
- **Binaries accumulate in git history.** The pack is checked on every
  `firmware/**` push and warns past 250 MB; see the README's Building section
  for the intended migration when it trips.
