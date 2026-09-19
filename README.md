# Serin CN105

Firmware and ESPHome configurations for controlling Mitsubishi heat pumps via the CN105 connector.

## Contents

- **`firmware/esphome/`** — Pre-built ESPHome firmware binaries (merged, ready to flash)
- **`firmware/homekit/`** — Pre-built [HomeKit firmware](https://github.com/akifbayram/mitsubishi-cn105-homekit) binaries
- **`firmware/matter/`** — Pre-built Matter firmware binaries (Apple Home, Google Home, Alexa)
- **`firmware/link/`** — Archived encrypted Link OTA and USB factory images; new signed plaintext OTA channels under `ota/`
- **`esphome/`** — ESPHome YAML configurations using the [MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome) component
- **`docs/`** — [ESPHome REST API](docs/esphome-rest-api.md) reference for third-party integrations

Every `firmware/` directory carries a `manifest.json` next to its binaries. That manifest — not this README — is the source of truth for versions and per-board builds; the web installer and the Link updater read it straight from `main`, so a release needs no site deploy.

### Release channels

The HomeKit firmware publishes on two channels:

| Channel | Manifest | Who reads it |
|---------|----------|--------------|
| Stable | `firmware/homekit/manifest.json` | The web installer, and every device's update check by default |
| Beta | `firmware/homekit/beta/manifest.json` | Devices with "Beta updates" switched on, and the installer's pre-release option |

Beta builds come from prerelease tags (`v0.2.6-beta.1`) and are written only into `firmware/homekit/beta/`. A stable release never touches that directory and a beta never touches stable, so the default install path is always the stable build. Only the newest beta is kept.

A device on the beta channel is offered whichever of the two manifests names the higher version. Once a stable release passes the beta it supersedes it, so testers roll back onto stable without a new beta being cut and cannot be stranded on an abandoned prerelease.

The Matter release workflow uses the same directory layout: stable tags write
`firmware/matter/manifest.json`, and prerelease tags write
`firmware/matter/beta/manifest.json` with `channel: beta`. Each release preserves
the other channel's files, and only the newest beta is kept. Matter firmware
already reads that beta URL when beta updates are enabled. The web installer's
Matter selection currently uses the stable manifest only.

## Supported Boards

| Board | Chip | ESPHome | HomeKit | Matter |
|-------|------|---------|---------|--------|
| M5Stack Atom S3 Lite | ESP32-S3 | Yes | Yes | Yes |
| M5Stack NanoC6 | ESP32-C6 | Yes | Yes | Yes |
| ESP32-C3 Mini | ESP32-C3 | — | Yes | — |
| ESP32 DevKit | ESP32 | — | Yes | — |

The Serin Link dial is a separate device with its own boards, published under
the IDs `link15` and `link21`. Its signed plaintext OTA feeds use
`firmware/link/ota/stable/manifest.json` and `firmware/link/ota/beta/manifest.json`.
The older encrypted feeds remain at `firmware/link/manifest.json` and
`firmware/link/beta/manifest.json` for legacy devices.

## Installation

Flash firmware directly from your browser at [serin-labs.github.io](https://serin-labs.github.io). Connect your board via USB and select ESPHome, HomeKit, or Matter. Reboot after flashing and follow the WiFi setup instructions; Matter builds derive their pairing code from the device MAC, so the flasher shows it without any manifest carrying a pairing payload.

Current Link firmware uses signed plaintext OTA images. The new feeds must be
published before firmware using their URLs ships; see the
[migration and rollout instructions](docs/release-validation.md#link-plaintext-ota-migration).
Legacy encrypted and plaintext OTA formats are not interchangeable.
`firmware/link/factory-manifest.json` describes the merged USB images used by
the Link flasher. Older encrypted updaters need a new factory image to migrate.

## Building

ESPHome binaries are built from `esphome/` by [`.github/workflows/esphome-firmware.yml`](.github/workflows/esphome-firmware.yml), which recompiles every supported board on each push to those configs and commits the merged binaries and manifest back to `firmware/esphome/`. The ESPHome version is pinned in [`requirements.txt`](requirements.txt) so a rebuild of unchanged configs produces unchanged binaries; Dependabot proposes the bumps. Each build job emits its own manifest fragment and the deploy job merges them, so adding a board is a single matrix entry.

HomeKit, Matter, and Serin Link binaries are built elsewhere and published into this repo by their own release workflows.

[`scripts/validate-manifests.py`](scripts/validate-manifests.py) checks both OTA
and factory manifests in pull requests and after firmware or validator changes.
It validates the manifest fields, board IDs, local paths, file hashes and sizes,
and flash-part ranges. Link plaintext images also need the production signature
and a matching embedded version. Factory images need the supported partition
layout and `dirty: false`. Legacy encrypted artifacts must match the archived
ciphertext hashes and metadata; their plaintext remains unverifiable here.
See [the release validation contract](docs/release-validation.md) for the exact
checks, limitations, and commands for validating staged releases.

The ESPHome, HomeKit and Matter workflows validate before committing and
pushing, and revalidate after a rebase before retrying a push. HomeKit and
Matter also wait for successful deployment before uploading GitHub Release
assets. Their workflow changes require these validation tools on `main`
first; see the [rollout order](docs/release-validation.md#rollout-order).
The Link staging tool's `--distribution` option validates the complete candidate
checkout before replacing a plaintext channel. It does not push; revalidate
immediately before publication and after any rebase. **Post-push CI cannot
prevent a broken direct push from going live.**

The validation workflow also reports the pack size: firmware images do not
delta-compress, so history grows by roughly every release forever, and past
250 MB the intended move is to publish binaries as GitHub Release assets and
point manifests at them. Before that migration, verify CORS and any consumers'
Range requirements on a throwaway release, and extend the local-file validation
contract to cover remote assets.

## License

The ESPHome configurations in `esphome/` and the documentation in `docs/` are [MIT licensed](LICENSE).

`firmware/` redistributes builds produced by other projects and is not covered by that grant. The HomeKit binaries are built from [mitsubishi-cn105-homekit](https://github.com/akifbayram/mitsubishi-cn105-homekit) (MIT); the Matter and Serin Link images are built from closed sources and are published here for installation and OTA delivery only.

## Related Repositories

| Repository | Description |
|------------|-------------|
| [Serin-Labs/serin-labs.github.io](https://github.com/Serin-Labs/serin-labs.github.io) | Web installer, setup guides, wiring references, and config generator |
| [akifbayram/mitsubishi-cn105-homekit](https://github.com/akifbayram/mitsubishi-cn105-homekit) | Native HomeKit firmware for Mitsubishi heat pumps |
| [echavet/MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome) | ESPHome CN105 climate platform component |
