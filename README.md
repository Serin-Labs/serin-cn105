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

### Link updates through an ESPHome controller

The official board configurations require ESPHome **2026.7.4 or newer**.
Both enable `serin_link.link_ota_credentials`
in the shared CN105 package. After installing a build with this setting and
connecting the controller to Wi-Fi, a bonded Link can use
**Settings → About → Details → Update**. Existing bonds remain valid.

When a bonded Link requests an update, the controller sends its Wi-Fi network
name and key over the encrypted ESP-NOW connection. Link uses these temporary
credentials to connect directly to the internet and download its own firmware.
It needs HTTPS and time synchronization access; the controller does not proxy
the download. This setting does not update the controller's firmware.

To disable credential sharing, add this override to your device YAML:

```yaml
serin_link:
  link_ota_credentials: false
```

Disabling it hides Link's Update action after the controller is updated.
Use this override with WPA-Enterprise (`eap:`) networks, which have no shared
Wi-Fi key to relay. The reusable `serin_link` component remains disabled by
default in configurations that do not import this package.

## Building

ESPHome binaries are built from `esphome/` by
[`.github/workflows/esphome-firmware.yml`](.github/workflows/esphome-firmware.yml).
Pushes to `main` that change the configs, build requirements, dependency checks,
or workflow rebuild both boards and publish the merged binaries and
manifest to `firmware/esphome/`. Each build job emits its own manifest fragment;
the validation job merges them, so adding a board is a single matrix entry.

Every pull request targeting `main` also builds both boards and validates the
assembled firmware and manifest. The read-only `ESPHome validation` check fails
if either build fails, is cancelled, or is skipped. PRs and manual runs on other
branches produce downloadable artifacts; publication is restricted to successful
push or manual runs on `main`. Configure `ESPHome validation` as a required check
after rollout, with a narrowly scoped exception for trusted firmware publishers;
see [activating the PR gate](docs/release-validation.md#esphome-pull-request-gate).

The release environment uses Linux x86_64 and Python 3.12. ESPHome is pinned
in [`requirements.txt`](requirements.txt), with its resolved Python dependencies
constrained by [`requirements-build.lock`](requirements-build.lock). Both board
configs pin ESP-IDF 5.5.5. Its separate Python environment is constrained by
[`requirements-idf.lock`](requirements-idf.lock) through `PIP_CONSTRAINT` during
compilation. CI starts with fresh environments and verifies both installed
package sets against their locks before accepting the build. The external
components use these tested revisions:

| Component | Revision |
| --- | --- |
| MitsubishiCN105ESPHome | `29133a9b84d826f6a6e9a3025f9c556460b0e0f8` |
| serin-link-core | `93bf46ffc6b63bba020d01e80e5e0bb4573906d5` (`v0.1.5-beta.1`) |

Shared YAML uses relative `!include` paths, so local builds and dashboard
imports resolve packages from the same selected checkout. Dashboard discovery
still points to `main`; pin the root package to a commit if you need to retain
a particular configuration. These pins control dependency versions, but do not
guarantee byte-identical binaries: build timestamps and the runner environment
can still differ.

To validate a checkout in a fresh Python 3.12 environment:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python scripts/check-python-lock.py requirements-build.lock
python scripts/check-esphome-packages.py
export ESPHOME_ESP_IDF_PREFIX="$(mktemp -d -t serin-esphome-idf.XXXXXX)"
export PIP_CONSTRAINT="$PWD/requirements-idf.lock"
esphome clean esphome/serin_esp32c6.yaml
esphome compile esphome/serin_esp32c6.yaml
esphome clean esphome/serin_esp32s3.yaml
esphome compile esphome/serin_esp32s3.yaml
"$ESPHOME_ESP_IDF_PREFIX"/penvs/*/bin/python scripts/check-python-lock.py requirements-idf.lock
```

Set the IDF constraints only after installing ESPHome: the two environments
intentionally use different versions of some tools. The fresh IDF prefix
prevents a previously cached environment from bypassing the constraints.
Cleaning each config removes build output tied to a previous IDF environment.

For an intentional dependency update, create a separate fresh Linux/Python 3.12
environment and install the proposed `esphome==VERSION` directly, without the
old constraints. Update both board configs' component and framework pins and
their `min_version` as needed, and coordinate the same pins with the website's
`esphome/generate-yaml.html`. Run the package-resolution check and compile both
boards before recording `python -m pip freeze` in `requirements-build.lock`.
For an IDF dependency update, build with a fresh `ESPHOME_ESP_IDF_PREFIX` and
without `PIP_CONSTRAINT`, then use that prefix's `penvs/*/bin/python -m pip
freeze --all` to refresh `requirements-idf.lock`. Retain both locks' explanatory
headers. Update `requirements.txt`, review every lock change, then repeat the
commands above in another clean environment. Validate both boards' generated
website YAML as well. Dependabot proposals require this
same review; a builder bump alone is insufficient.

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
