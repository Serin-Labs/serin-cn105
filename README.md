# Serin CN105

Firmware and ESPHome configurations for controlling Mitsubishi heat pumps via the CN105 connector.

## Contents

- **`firmware/esphome/`** — Pre-built ESPHome firmware binaries (merged, ready to flash)
- **`firmware/homekit/`** — Pre-built [HomeKit firmware](https://github.com/akifbayram/mitsubishi-cn105-homekit) binaries
- **`esphome/`** — ESPHome YAML configurations using the [MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome) component

## Supported Boards

| Board | Chip | ESPHome | HomeKit |
|-------|------|---------|---------|
| M5Stack Atom S3 Lite | ESP32-S3 | Yes | Yes |
| M5Stack NanoC6 | ESP32-C6 | Yes | Yes |
| ESP32-C3 Mini | ESP32-C3 | — | Yes |
| ESP32 DevKit | ESP32 | — | Yes |

## Installation

Flash firmware directly from your browser at [serin-labs.github.io](https://serin-labs.github.io). Connect your board via USB and select ESPHome or HomeKit. Reboot after flashing and follow the WiFi setup instructions.

## Related Repositories

| Repository | Description |
|------------|-------------|
| [Serin-Labs/serin-labs.github.io](https://github.com/Serin-Labs/serin-labs.github.io) | Web installer, setup guides, wiring references, and config generator |
| [akifbayram/mitsubishi-cn105-homekit](https://github.com/akifbayram/mitsubishi-cn105-homekit) | Native HomeKit firmware for Mitsubishi heat pumps |
| [echavet/MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome) | ESPHome CN105 climate platform component |
