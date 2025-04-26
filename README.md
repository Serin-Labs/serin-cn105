# Serin – Mitsubishi HVAC Controller

This package aims to make it simpler to make your Mitsubishi HVAC unit smarter, more private, and easier to control. This package brings local, cloud-free control to your HVAC system using community driven open source software.

## Why?
- **100% Local Control** – No cloud, no fees, no privacy worries.
- **Open Source** – Powered by ESPHome and the community. 
- **Compact & Clean** – Installs inside your Mitsubishi HVAC unit for a seamless look.
- **DIY or Pre-Assembled** – Build it yourself or order a ready-to-go kit.

## What You’ll Need

### Option A: Purchase Parts Individually
- **Device:**
  - [M5Stack Atom S3 Lite](https://www.digikey.com/en/products/detail/m5stack-technology-co-ltd/C124/18070571) or [NanoC6](https://www.digikey.com/en/products/detail/m5stack-technology-co-ltd/C125/22571399)
- **Cable:**
  - [JST PAP-05V-S connector](https://www.digikey.com/en/products/detail/jst-sales-america-inc/pap-05v-s/759977) (CN105 port on the HVAC unit)
  - [Grove HY2.0-4P connector](https://www.digikey.com/en/products/detail/seeed-technology-co-ltd/110990027/5482567) (ESP32 side)

### Option B: Preassembled Kit
- **Ready-to-go kit** including the device, custom cable, and pre-flashed firmware — [order here](#).

*If you purchase the kit, you can skip wiring and firmware flashing. It's ready to connect to your Wi-Fi and Mitsubishi HVAC unit.*

## Setup Guide

See the [setup guide](https://serin-labs.github.io/setup.html) for step-by-step instructions.

## Wiring Reference

For detailed pinouts and cable assembly, see the [wiring reference](https://serin-labs.github.io/wiring.html).

## YAML Generator

Use the [YAML config generator](https://serin-labs.github.io/generate-yaml.html) to create a ready-to-use ESPHome configuration for your device, including options for remote temperature sensors, vane control, and advanced diagnostics.

## Gratitude

Special thanks to [echavet](https://github.com/echavet/MitsubishiCN105ESPHome), the ESPHome community, [SwiCago](https://github.com/SwiCago/HeatPump), [geoffdavis](https://github.com/geoffdavis/esphome-mitsubishiheatpump), and all contributors whose work made this guide possible.

## References
- [SwiCago/HeatPump](https://github.com/SwiCago/HeatPump)
- [Hacking a Mitsubishi Heat Pump (chrdavis)](https://chrdavis.github.io/hacking-a-mitsubishi-heat-pump-Part-1/)
- [CN105 Connector (casualhacker.net)](https://casualhacker.net/post/2017-10-24-CN105_Connector)
- [geoffdavis/esphome-mitsubishiheatpump](https://github.com/geoffdavis/esphome-mitsubishiheatpump)
- [echavet/MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome)
- [muart-group](https://github.com/muart-group)

## Disclaimer & Safety

Modifying HVAC systems may void warranties and carries risks. Always turn off power to your HVAC unit before connecting or disconnecting any cables. This project is provided as-is, with no warranties or liability. Proceed with care.