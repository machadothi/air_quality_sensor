# Bluetooth (ESP32)

On an ESP32 the air monitor is also a Bluetooth LE device, next to Wi-Fi and
MQTT:
- **Phone app.** It speaks the "BLE Sensor" protocol, so the BLE Sensor phone
  app finds it in its scan, as board type **ESP32 Air**, connects, and shows and
  configures it.
- **Home Assistant.** It broadcasts its readings as **BTHome**, which Home
  Assistant picks up without Wi-Fi or a broker.

The ESP8266 has no Bluetooth; there everything here is simply left out.

- [What it sends](#what-it-sends)
- [GATT service](#gatt-service)
- [BTHome](#bthome)
- [Settings](#settings)
- [Trying it](#trying-it)
- [Limits](#limits)

The code is `firmware/ble.py`, started by `app.py` on the ESP32.

## What it sends

MicroPython has a single advertising slot, so the board alternates two
packets every second:

| Packet | Content | Connectable |
|---|---|---|
| **App packet** | flags · 128-bit service UUID `a7e40000-5c2b-4f1a-9d3e-6b8c0f2e1d47` · manufacturer data: company `0x02FF`, board id `0x0C`, protocol version `1` | yes |
| **BTHome packet** | flags · service data `0xFCD2`: packet id, temperature, humidity, CO2 | yes |

The scan response carries the name, by default `Air-Monitor-XXXX` (the last 4
hex digits of the Bluetooth address).

While a phone is connected, only the BTHome packet goes out (not
connectable), so Home Assistant keeps getting readings.

## GATT service

Service `a7e40000-5c2b-4f1a-9d3e-6b8c0f2e1d47`. Characteristic UUIDs are
`a7e400XX-5c2b-4f1a-9d3e-6b8c0f2e1d47`. All values are packed little-endian,
and their layouts match the Thunderboard firmware's `ble_protocol.h`.

| XX | Name | Access | Bytes | Content |
|---|---|---|---|---|
| 01 | Env | read, notify (every 2 s) | 27 | Thunderboard layout; only temperature and humidity are filled in (`valid` bits 0 and 1) |
| 06 | Info | read | 4 | protocol version `1`, board id `0x0C`, sensors `0x41` (bit 0 temperature/humidity, bit 6 air quality), reserved |
| 07 | Command | write | 1 | `0x02` factory reset, `0x03` reboot, `0x04` identify (the display flashes for 3 s) |
| 08 | Name | read, write | ≤ 20 | UTF-8; stored, advertised from the next advertising round |
| 09 | Display | read, write | 7 | `present` (u8), `page_mask` (u16), `page_ms` (u16, 1000–60000), `flags` (u8, bit 0 = rotated 180°), page bits 16–23 (u8). A 5-byte write (Thunderboard clients) leaves the rest as it is. |
| 0A | **Air** | read, notify (every 2 s) | 22 | see below |
| 0B | **System** | read, notify (every 5 s) | 32 | the ESP32 itself, see below |
| 0C | **Calibration** | read, write, notify (every 5 s) | 20 | temperature offset and self-heating measurement, see below |
| 0D | **Time** | read, write | 12 / 7 | the board's clock, see below |
| 0E | **Wi-Fi** | read, write, notify (on change) | ≤ 512 | network, scan, MQTT on/off, see below |
| 0F | **Weather** | read, write | ≤ 128 | Open-Meteo weather and its place, see below |

**Air** (new for this board):

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | uptime, ms |
| 4 | u8 | state: 0 normal, 1 warm-up, 2 start-up, 3 invalid, `0xFF` no sensor |
| 5 | u8 | AQI 1–5 (UBA), 0 when not normal |
| 6 | u16 | eCO2, ppm, 0 when not normal |
| 8 | u16 | TVOC, ppb, 0 when not normal |
| 10 | u8 | raw DEVICE_STATUS register |
| 11 | 3 × u8 | ENS160 firmware: major, minor, release |
| 14 | u16 | raw resistance R1 (ohms = 2^(raw/2048)), 0 = none yet |
| 16 | u16 | raw resistance R4 |
| 18 | i16 | compensation temperature the ENS160 uses, °C × 100 (`0x7FFF` = none yet) |
| 20 | u16 | compensation humidity, % × 100 |

The first 10 bytes are the original layout, so a client that reads only those
still works.

**System** (the ESP32):

| Offset | Type | Field |
|---|---|---|
| 0 | u32 | uptime, s |
| 4 | u32 | free RAM, bytes |
| 8 | i16 | chip temperature, °C × 100 (die temperature, uncalibrated; `0x7FFF` = n/a) |
| 10 | i8 | Wi-Fi RSSI, dBm (0 = not connected) |
| 11 | u8 | flags: bit 0 Wi-Fi, bit 1 MQTT, bit 2 Bluetooth connected |
| 12 | 4 × u8 | IP address |
| 16 | u16 | CPU, MHz |
| 18 | u8 | last reset: 1 power on, 2 reset pin/USB, 3 watchdog, 4 deep sleep, 5 software |
| 19 | 3 × u8 | MicroPython version |
| 22 | u16 | sensor errors (a sensor stopped answering) |
| 24 | u16 | ENS160 checksum errors |
| 26 | u32 | seconds the AHT21 spent above 80 %RH since start |
| 30 | u16 | reserved |

**Calibration** (read):

| Offset | Type | Field |
|---|---|---|
| 0 | i16 | temperature offset in use, °C × 100 |
| 2 | u8 | automatic daily measurement on (1) / off (0) |
| 3 | u8 | measurement state: 0 idle, 2 cooling, 3 done, 4 failed |
| 4 | u16 | seconds since the measurement started |
| 6 | u16 | longest cooling time, s |
| 8 | i16 | warm temperature (uncorrected, before cooling), °C × 100, `0x7FFF` = none |
| 10 | i16 | current uncorrected temperature, °C × 100 |
| 12 | i16 | last result, °C × 100, `0x7FFF` = none |
| 14 | u32 | seconds since the last result, `0xFFFFFFFF` = none |
| 18 | u8 | why the last run failed: 1 sensor not answering, 2 room temperature changed, 3 cancelled, 4 out of range |
| 19 | u8 | reserved |

Write 2 bytes (`i16` offset × 100) to set the offset, or 4 bytes: offset,
automatic on/off, command (0 none, 1 start a measurement, 2 cancel). See
[sensors.md](sensors.md#temperature-offset) for the measurement.

**Time** (read, 12 bytes): u32 Unix time UTC (0 = not known), i16 standard
offset from UTC in minutes, u8 summer-time rule (0 none, 1 EU, 2 US), u8 source
(0 unknown, 1 internet, 2 phone), i16 offset in effect now (minutes), u16
reserved. **Write** 7 bytes: u32 Unix time, i16 standard offset, u8 rule. The
app does this on every connect, from the phone's clock and time zone; with
Wi-Fi the board also syncs from the internet (NTP) every 6 hours.

**Wi-Fi** (read): u8 state (0 idle, 1 connecting, 2 connected, 3 failed), u8
failure (1 wrong password, 2 not found, 3 other), i8 RSSI, 4 bytes IP, u8 SSID
length + SSID, u8 scanning, u8 flags (bit 0 MQTT on, bit 1 MQTT connected,
bit 2 online: internet reachable), u8
count, then per network: u8 name length + name + i8 RSSI (at most 10).
**Write**: `1` scan (the board blocks ~3 s), `2, len, SSID, len, password`
connect (stored in `settings.json`), `3` back to `config.json`'s network, `4` /
`5` MQTT on / off. The password travels unencrypted over Bluetooth.

**Weather** (read): u8 flags (bit 0 on, bit 1 fresh data, bit 2 online), i16
temperature × 10, i16 feels-like × 10, u8 humidity %, u8 WMO weather code, u8
day (1) / night (0), i16 wind m/s × 10, i16 today's high × 10, i16 low × 10, u8
rain chance %, u16 data age in minutes (`0xFFFF` = none), u8 length + place,
u8 length + last error, u8 place found automatically (1). Values are `0x7FFF`
when there's no fresh data. **Write**: `1, len, name` set the place (empty =
find it from the internet address), `2` / `3` weather on / off, `4` refresh now.

**Display page bits** (`page_mask`): bit 0 temperature, bit 1 humidity,
bit 10 air quality, bit 11 eCO2, bit 12 TVOC, bit 13 dew point, bit 14 air
sensor details, bit 15 system, bit 16 clock, bit 17 weather (in the 7th byte of
the Display value: page bits 16–23). Bits 0–9 are the same as on the Thunderboard.
- **Order is kept.** A mask has no order: the pages you keep stay in their
  current order, newly enabled ones are added at the end. The order itself can
  be changed over MQTT (`/display`).
- **At least one page.** A write with no pages, or a time outside 1–60 s, is
  ignored and the old value written back.

There is no Motion, Button, LED or Config characteristic: this board has no
IMU, button or LED, and its sensors always run. The app hides those parts for
this board.

## BTHome

Home Assistant finds the board as a BTHome device under Settings → Devices &
services; confirm it once. Objects sent:

| BTHome object | Value |
|---|---|
| `0x00` packet id | changes every packet, so Home Assistant ignores repeats |
| `0x02` temperature | 0.01 °C |
| `0x03` humidity | 0.01 % |
| `0x08` dew point | 0.01 °C |
| `0x12` CO2 | ppm (the ENS160's eCO2), only when the sensor is ready |
| `0x13` TVOC | µg/m³, ethanol-equivalent (see [sensors.md](sensors.md#ratings)), only when ready |

The air-quality index has no BTHome type; it's available over MQTT.

If you already use the MQTT readings in Home Assistant, you'll have
temperature and humidity twice. Either ignore the BTHome device, or turn it
off (`"bthome": false`).

## Settings

In `config.json` (all optional):

```json
"bluetooth": {
    "enabled": true,
    "bthome": true,
    "name": ""
}
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | true | false = no Bluetooth at all |
| `bthome` | true | false = only the app packet |
| `name` | `""` | `""` = `Air-Monitor-XXXX`; a name set from the app is stored in `settings.json` and wins |

## Trying it

- **BLE Sensor app:** the radar shows the board as "ESP32 Air".
  - **Live:** air-quality card, eCO2, TVOC, temperature, humidity.
  - **Charts:** includes eCO2 and TVOC.
  - **Control:** identify, reboot, factory reset.
  - **Settings:** name and display pages.
- **nRF Connect** (Nordic, any phone): shows the service and lets you read each
  characteristic.
- **From a Linux PC** with the BLE Sensor Python client:
  ```sh
  ble-sensor scan
  ble-sensor -n Air-Monitor-XXXX read        # temperature, humidity, AQI, eCO2, TVOC
  ble-sensor -n Air-Monitor-XXXX display --pages air,temperature --page-time 8
  ```

## Limits

- **Rejected writes aren't refused over the air.** MicroPython can't answer a
  write with an ATT error. A rejected Display or Name write is replaced by the
  old value instead, and a client sees that when it reads again.
- **One phone at a time.**
- **Name changes** show in scans after the next advertising round (about a
  second); the GAP device name some phones cache may need a reconnect.
