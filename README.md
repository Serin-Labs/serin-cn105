# Serin CN105

Firmware and ESPHome configurations for controlling Mitsubishi heat pumps via the CN105 connector.

## Contents

- **`firmware/esphome/`** — Pre-built ESPHome firmware binaries (merged, ready to flash)
- **`firmware/homekit/`** — Pre-built [HomeKit firmware](https://github.com/akifbayram/mitsubishi-cn105-homekit) binaries
- **`firmware/matter/`** — Pre-built Matter firmware binaries (Apple Home, Google Home, Alexa)
- **`firmware/link/`** — Encrypted OTA images for the Serin Link dial
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

## Supported Boards

| Board | Chip | ESPHome | HomeKit | Matter |
|-------|------|---------|---------|--------|
| M5Stack Atom S3 Lite | ESP32-S3 | Yes | Yes | Yes |
| M5Stack NanoC6 | ESP32-C6 | Yes | Yes | Yes |
| ESP32-C3 Mini | ESP32-C3 | — | Yes | — |
| ESP32 DevKit | ESP32 | — | Yes | — |

The Serin Link dial is a separate device with its own boards, published under the ids `link15` and `link21` in `firmware/link/manifest.json`.

## Installation

Flash firmware directly from your browser at [serin-labs.github.io](https://serin-labs.github.io). Connect your board via USB and select ESPHome, HomeKit, or Matter. Reboot after flashing and follow the WiFi setup instructions; Matter builds derive their pairing code from the device MAC, so the flasher shows it without any manifest carrying a pairing payload.

The Link updates itself over the air instead: it fetches its manifest and image from this repo, decrypts the image in-stream, and re-verifies the written slot's SHA-256 before switching boot partitions. Only ciphertext is hosted here.

## Building

ESPHome binaries are built from `esphome/` by [`.github/workflows/esphome-firmware.yml`](.github/workflows/esphome-firmware.yml), which recompiles every supported board on each push to those configs and commits the merged binaries and manifest back to `firmware/esphome/`. The ESPHome version is pinned in [`requirements.txt`](requirements.txt) so a rebuild of unchanged configs produces unchanged binaries; Dependabot proposes the bumps. Each build job emits its own manifest fragment and the deploy job merges them, so adding a board is a single matrix entry.

HomeKit, Matter, and Serin Link binaries are built elsewhere and published into this repo by their own release workflows.

Whatever writes them, [`scripts/validate-manifests.py`](scripts/validate-manifests.py) runs on every push touching `firmware/` and fails if a manifest is malformed, names a file that is not there, or disagrees with the binary's hash. It also reports the pack size: firmware images do not delta-compress, so history grows by roughly every release forever, and past 250 MB the intended move is to publish binaries as GitHub Release assets and point manifests at them. Two things need checking on a throwaway release before committing to that — that asset downloads still send CORS headers after the redirect to `objects.githubusercontent.com`, and that they honour `Range` requests, which the Link's OTA depends on.

## License

The ESPHome configurations in `esphome/` and the documentation in `docs/` are [MIT licensed](LICENSE).

`firmware/` redistributes builds produced by other projects and is not covered by that grant. The HomeKit binaries are built from [mitsubishi-cn105-homekit](https://github.com/akifbayram/mitsubishi-cn105-homekit) (MIT); the Matter and Serin Link images are built from closed sources and are published here for installation and OTA delivery only.

## Related Repositories

| Repository | Description |
|------------|-------------|
| [Serin-Labs/serin-labs.github.io](https://github.com/Serin-Labs/serin-labs.github.io) | Web installer, setup guides, wiring references, and config generator |
| [akifbayram/mitsubishi-cn105-homekit](https://github.com/akifbayram/mitsubishi-cn105-homekit) | Native HomeKit firmware for Mitsubishi heat pumps |
| [echavet/MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome) | ESPHome CN105 climate platform component |
