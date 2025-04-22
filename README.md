# Serin – Mitsubishi ESP32 Wi-Fi Adapter

**Serin is my nickname for our mini-split HVAC units—because they keep things serene.** Fun fact: *serin* also means "cool" in Turkish! This project adds local Wi-Fi control to Mitsubishi mini-splits using an off-the-shelf device and open-source software.

## Why Serin?

Built around the awesome work of [echavet](https://github.com/echavet/MitsubishiCN105ESPHome), [SwiCago](https://github.com/SwiCago/HeatPump), and [geoffdavis](https://github.com/geoffdavis/esphome-mitsubishiheatpump), a Serin device provides:

✅ **100% Local Control** – No cloud, no fees, full privacy  
✅ **Open Source** – Powered by ESPHome  
✅ **Compact & Clean** – Small enough to hide inside your mini-split  
✅ **DIY or Pre-Assembled** – Build it yourself or buy a ready-to-go kit on [Etsy](#)

Visit [serin-labs](#) for full install instructions and a [YAML config generator](#) so you can customize the device configuration based on your needs, like enalbing a remote temperature sensor, vane control options, and advanced diagnostics.

## Getting Started

### 1. Gather Your Hardware
- Choose a device:
  - [M5Stack Atom S3 Lite](https://shop.m5stack.com/products/atoms3-lite-esp32s3-dev-kit)
  - [M5Stack NanoC6](https://shop.m5stack.com/products/m5stack-nanoc6-dev-kit)
  - [Etsy kits](#) with cable and pre-flashed firmware
- Get a CN105 (JST-PAP-05V-S) to Grove (HY2.0-4P) cable (included in Etsy kits)

### 2. Flash Firmware
If using a kit, firmware is pre-flashed and you can skip to step 3. Otherwise:

**Option A: ESPHome Dashboard**
- Use the [YAML generator](#)
- Create and upload the config in ESPHome Dashboard
- Flash to your device

**Option B: ESPHome Web**
- Download a pre-built binary
- Flash using [ESPHome Web](https://web.esphome.io/)

### 3. Connect to Wi-Fi
After flashing and powering on, connect your device to your network:

**Option A: USB-C**
- Plug into your computer
- Visit the [install](#) page and click “Connect to Wi-Fi”

**Option B: Wi-Fi Setup Mode**
- Join the device’s network: `serin-cn105-xxxxx`
- Go to [`http://192.168.4.1`](http://192.168.4.1)
- Enter Wi-Fi credentials and connect

### 4. Home Assistant Integration
- The device will appear in ESPHome automatically
- Once adopted, it’ll also be auto-discovered by Home Assistant
- Click “Configure” in Home Assistant when prompted

### 5. Connect to HVAC
- Power off the HVAC at the breaker. Open the panel and locate the CN105 port.
- Connect the CN105 to Grove cable to the mini-split and device, respectively.
- Tuck the device safely inside and close the panel. Restore power.

### 6. Optional: Web Interface
- Access the device’s local IP in your browser for direct control (no Home Assistant needed)

## Disclaimer & Safety

Working on HVAC systems can be risky and may void warranties. Proceed only if you're confident. This project is provided as-is, without warranty or liability.

## Gratitude

Huge thanks to [echavet](https://github.com/echavet/MitsubishiCN105ESPHome), the ESPHome community, and giants like [SwiCago](https://github.com/SwiCago/HeatPump) and [geoffdavis](https://github.com/geoffdavis/esphome-mitsubishiheatpump).
