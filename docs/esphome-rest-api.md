# ESPHome REST API

The Serin ESPHome firmware enables `web_server` (see `esphome/common/web_server.yaml`), which exposes an HTTP API for reading and controlling every entity on the device. This lets you integrate the heat pump with anything that can speak HTTP — SmartThings Edge drivers, Node-RED, shell scripts — without Home Assistant or MQTT.

This applies to the **ESPHome** firmware only. The HomeKit firmware has no REST API; its control surface is a WebSocket at `/ws`.

> [!NOTE]
> ESPHome does not officially document the climate endpoints, so they carry no compatibility guarantee across releases. Verified against ESPHome **2026.5.3**, the version in `firmware/esphome/`.

## Base URL and auth

```
http://<device-ip>/
```

The default Serin config sets no `auth:` on `web_server` and no `encryption:` on `api:`. Anything on your LAN can read state and send commands. Add credentials if that matters:

```yaml
web_server:
  version: 3
  auth:
    username: serin
    password: !secret web_password
```

Requests then need HTTP Basic auth.

## URL scheme

```
/<domain>/<entity-name>[/set?<param>=<value>]
```

`<entity-name>` is the entity's **name**, URL-encoded — not its object ID. To find the exact names, `GET /events` and read the `id` field of each `state` event; the value is literally `<domain>/<name>`, so `"id": "climate/Serin"` means the URL is `/climate/Serin`.

For a default Serin install (`friendly_name: "Serin"`, climate `name: None`) that gives:

| Entity | URL |
|--------|-----|
| Heat pump | `/climate/Serin` |
| Vertical vane | `/select/Vertical%20Vane` |
| Horizontal vane | `/select/Horizontal%20Vane` |
| WiFi signal | `/sensor/Signal%20dB` |

> [!WARNING]
> ESPHome 2026.5 and 2026.6 also accept the older object-ID form (`/climate/serin`, `/select/vertical_vane`) but log a deprecation warning. It is **removed in 2026.7.0**. Use entity names.

Reads are `GET`. Commands are `POST` to `/set` with query-string parameters (`GET` also works, but `POST` is the convention).

## Reading state

```bash
curl http://serin.local/climate/Serin
```

```json
{
  "id": "climate/Serin",
  "state": "22.0",
  "mode": "COOL",
  "action": "COOLING",
  "fan_mode": "AUTO",
  "current_temperature": "23.4",
  "target_temperature": "22.0"
}
```

Add `?detail=all` to also get the entity's capabilities — `modes`, `fan_modes`, `swing_modes`, `presets`, `min_temp`, `max_temp`, `step`. Use this to discover what your unit actually supports rather than hardcoding it:

```bash
curl 'http://serin.local/climate/Serin?detail=all'
```

Temperatures are returned as **strings** at the entity's configured accuracy, and become the string `"NA"` when unavailable. `state` mirrors `action` when the unit reports one, otherwise the target temperature.

## Sending commands

```
POST /climate/<name>/set?<param>=<value>[&<param>=<value>...]
```

Parameters can be combined in one request; all of them apply as a single climate call.

| Parameter | Values |
|-----------|--------|
| `mode` | `OFF`, `AUTO`, `COOL`, `HEAT`, `FAN_ONLY`, `DRY` |
| `fan_mode` | `AUTO`, `QUIET`, `LOW`, `MEDIUM`, `MIDDLE`, `HIGH` |
| `target_temperature` | Number, 15–31 in 0.5 steps |
| `target_temperature_low` / `_high` | Numbers — dual-setpoint builds only |
| `swing_mode` | `OFF`, `VERTICAL`, `HORIZONTAL`, `BOTH` — only if `swing_mode` is enabled in `cn105.yaml` |
| `preset` | Only if the build defines presets |

The mode and fan lists above match the `supports:` block in `esphome/common/cn105.yaml`. If you customize that file, query `?detail=all` for the real lists.

```bash
# Cool to 22°C
curl -X POST 'http://serin.local/climate/Serin/set?mode=COOL&target_temperature=22'

# Fan speed only
curl -X POST 'http://serin.local/climate/Serin/set?fan_mode=QUIET'

# Off
curl -X POST 'http://serin.local/climate/Serin/set?mode=OFF'
```

A command returns `200` with an empty body as soon as it is queued — it does not wait for the heat pump to acknowledge. Confirm the result by re-reading state or watching `/events`.

Unknown entity names return `404`. Unrecognized parameter values are ignored rather than rejected, so a typo'd `mode` returns `200` and changes nothing.

## Vane control

The vanes are `select` entities. Their options come from the heat pump at runtime, so query them rather than assuming:

```bash
curl 'http://serin.local/select/Vertical%20Vane?detail=all'
curl -X POST 'http://serin.local/select/Vertical%20Vane/set?option=Swing'
```

Other entities you can enable in `cn105.yaml` follow the same `GET` for state, `POST` for action pattern, with their own action names:

| Domain | Command |
|--------|---------|
| `switch` | `/switch/<name>/turn_on`, `/turn_off`, `/toggle` |
| `number` | `/number/<name>/set?value=…` |
| `button` | `/button/<name>/press` |
| `sensor`, `binary_sensor`, `text_sensor` | read-only |

## Live updates

```bash
curl -N http://serin.local/events
```

`/events` is a [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/EventSource) stream. On connect it emits a `state_detail_all` event per entity (full capabilities), then a `state` event on every change, plus periodic `ping` and `log` events. Payloads are the same JSON as the `GET` endpoints.

Prefer this over polling — it is push-based, cheap on the device, and gives you the entity name list for free.

```js
const es = new EventSource('http://serin.local/events')
es.addEventListener('state', (e) => {
  const s = JSON.parse(e.data)
  if (s.id === 'climate/Serin') console.log(s.mode, s.current_temperature)
})
```

## Discovery

The device advertises itself over mDNS as `_esphomelib._tcp` and is reachable at `<name>.local` (`serin.local` by default). Integrations that need to find the device without a static IP can browse for that service type.

## See also

- [ESPHome Web Server API](https://esphome.io/web-api/) — documents the non-climate domains
- [`esphome/common/cn105.yaml`](../esphome/common/cn105.yaml) — which entities exist and what the heat pump supports
