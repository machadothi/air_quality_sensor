# Communication

- [I2C: sensors and display](#i2c-sensors-and-display)
- [Wi-Fi](#wi-fi)
- [MQTT](#mqtt)
- [Home Assistant](#home-assistant)
- [config.json](#configjson)

## I2C: sensors and display

One bus, bit-banged by `machine.SoftI2C` at 400 kHz on GPIO5 (SCL) / GPIO4 (SDA):

| Device | Address | Traffic |
|---|---|---|
| AHT21 | 0x38 | every 2 s: "measure" command, then 7 bytes 80 ms later |
| ENS160 | 0x53 | every loop: 1 status byte; once a second 5 data bytes; every 2 s 4 bytes of compensation |
| SSD1306 | 0x3C | 1 KB frame per redraw (~25 ms), 10 frames per page change |

Register details are in [sensors.md](sensors.md).

## Wi-Fi

The network can also be chosen in the app (ESP32): Settings → Wi-Fi, time &
MQTT → Choose network. It's stored in `settings.json` and wins over
`config.json`; "Use configured" goes back.

`net.py` uses the station interface (`network.WLAN(network.STA_IF)`) and
switches off the ESP8266's default access point, which MicroPython leaves on
as an open-looking network called `MicroPython-xxxxxx`.

The ESP8266 stores the last Wi-Fi credentials in its own flash and reconnects
by itself after a drop; `net.py` only calls `connect()` again if it hasn't
reconnected after 30 s.

## MQTT

MQTT 3.1.1 via `umqtt.simple`, QoS 0, keepalive 60 s (pinged every 30 s).

### Topics

`<client_id>` is `mqtt.client_id` from `config.json` (e.g. `air-monitor`).

| Topic | Direction | Retained | Content |
|---|---|---|---|
| `esp/air_quality_sensor` (`mqtt.topic_state`) | board → | yes | readings, every `publish_s`; retained so a new subscriber gets the latest at once |
| `esp/<client_id>/request` (`mqtt.topic_sub`) | → board | no | a request, plain text |
| `esp/<client_id>/response` (`mqtt.topic_pub`) | board → | no | the answer, JSON |
| `esp/<client_id>/availability` | board → | yes | `online`; `offline` sent by the broker if the board vanishes (last will) |
| `homeassistant/sensor/air_monitor_<chip id>/<key>/config` | board → | yes | discovery, only if enabled |

### Readings

```json
{"temperature": 22.4, "humidity": 48.6, "dew_point": 11.2, "absolute_humidity": 9.6,
 "eco2": 812, "tvoc": 164, "aqi": 2, "state": "normal", "status": 129}
```

| Key | Unit | Notes |
|---|---|---|
| `temperature` | °C | 1 decimal, offset applied |
| `humidity` | % RH | 1 decimal |
| `dew_point` | °C | from temperature and humidity ([sensors.md](sensors.md#derived-values)) |
| `absolute_humidity` | g/m³ | same |
| `eco2` | ppm | equivalent CO2, estimated from VOCs (not an NDIR CO2 sensor); `null` until the ENS160 is ready |
| `tvoc` | ppb | total volatile organic compounds; `null` until ready |
| `aqi` | 1–5 | UBA scale: 1 excellent, 2 good, 3 moderate, 4 poor, 5 unhealthy; `null` until ready |
| `state` | | `normal`, `warm-up`, `start-up`, `invalid` or `no sensor` |
| `status` | | raw ENS160 status register, for debugging |

Values are **averages** over the publish interval (60 samples of the ENS160,
30 of the AHT21 per minute), which smooths noise.

### Requests

Publish the text to the request topic; the JSON answer comes on the response topic.

| Request | Answer |
|---|---|
| `/read_all` | current (not averaged) readings, same keys as above |
| `/status` | `ip`, `wifi`, `wifi_rssi`, `mqtt`, `bluetooth`, `uptime_s`, `free_ram`, `lowest_free_ram`, `cpu_mhz`, `reset_cause`, `micropython`, `chip_temperature` (ESP32), `sensor_state`, `sensor_errors`, `sensor_integrity_errors`, `ens160_firmware`, `humid_s` |
| `/display` | `{"present": true, "pages": [...], "page_s": 5, "available": [...]}` |
| `/display {"pages": [...], "page_s": 8, "rotate": true}` | changes the pages (order counts), seconds per page (1–60) and/or the 180° rotation; any key may be left out; stored in `settings.json`; answers like `/display`, or with `error` |
| `/display/next` | moves the display to the next page; answers the page name |
| `/offset`, `/offset -2.0` | the temperature offset; set it (°C, −10 to 10, stored) |
| `/calibrate`, `/calibrate start`, `/calibrate cancel`, `/calibrate auto on/off` | self-heating measurement (ESP32): status, start, cancel, daily on/off; see [sensors.md](sensors.md#temperature-offset) |
| `/topics` | the topics in use and the accepted requests |
| `/reboot` | answers, then restarts the board after 1 s |

Example with the mosquitto clients (`sudo apt install mosquitto-clients`):

```sh
mosquitto_sub -h <broker> -u <user> -P '<password>' -t 'esp/#' -v &
mosquitto_pub -h <broker> -u <user> -P '<password>' -t esp/air-monitor/request -m /status
```

## Home Assistant

**Auto-discovery (recommended).** Set `"home_assistant_discovery": true` in
`mqtt`, then `tools/deploy.sh --config`. After each MQTT connect the board
publishes retained discovery messages (`firmware/home_assistant.py`), and an
**Air Monitor** device appears under Settings → Devices & services → MQTT
with these entities:

| Entity | Device class | Unit |
|---|---|---|
| Temperature | temperature | °C |
| Humidity | humidity | % |
| eCO2 | carbon_dioxide | ppm |
| TVOC | volatile_organic_compounds_parts | ppb |
| Air quality index | aqi | |
| Dew point | temperature | °C |
| Absolute humidity | absolute_humidity | g/m³ |
| Sensor state (diagnostic) | | |

All of them show "unavailable" when the board is offline (availability topic).
If you had YAML sensors on the same topic, delete them to avoid duplicates. To
remove the device later, publish an empty retained message to each of its
`homeassistant/sensor/.../config` topics.

**YAML instead**, in `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "Air eCO2"
      state_topic: "esp/air_quality_sensor"
      value_template: "{{ value_json.eco2 }}"
      unit_of_measurement: "ppm"
      device_class: carbon_dioxide
      availability_topic: "esp/air-monitor/availability"
```

and the same for `temperature`, `humidity`, `tvoc` and `aqi`.

### Why MQTT

| Option | Fit for this board |
|---|---|
| **MQTT** (used) | light, standard, HA native; the broker also lets other clients (the [phone app](android-app.md), scripts, `mosquitto_sub`) read and send requests |
| ESPHome | the most HA-native (its own API, OTA updates, supports ENS160/AHT21/SSD1306), but replaces MicroPython with YAML + C++ |
| HTTP | the board would need a web server, HA would poll; slower and heavier |
| Bluetooth (BTHome) | the ESP8266 has no Bluetooth |

## config.json

On the board (`config.json`) and on the PC (`firmware/config.json`,
git-ignored). Only `wifi`, `mqtt` (server, client_id, username, password,
topic_sub, topic_pub) are required; the rest falls back to
`DEFAULTS` in `firmware/app.py`. Template: `firmware/config.example.json`.

| Key | Default | Meaning |
|---|---|---|
| `esp` | – | ignored: the board type is detected |
| `wifi.ssid` / `wifi.password` | | your network |
| `mqtt.enabled` | true | false = no MQTT; switchable in the app (Settings → Wi-Fi, time & MQTT), stored in `settings.json` |
| `mqtt.server` | | broker IP or host name |
| `mqtt.port` | 0 (= 1883) | |
| `mqtt.client_id` | | unique per device; part of the topics |
| `mqtt.username` / `mqtt.password` | | broker login |
| `mqtt.topic_sub` / `topic_pub` | | request/response topics; `{client_id}` is replaced |
| `mqtt.topic_state` | `esp/air_quality_sensor` | readings topic |
| `mqtt.publish_s` | 60 | publish interval, s; readings are averaged over it |
| `mqtt.home_assistant_discovery` | false | see above |
| `mqtt.device_name` | `Air Monitor` | device name in HA |
| `pins.<board>.i2c_scl` / `i2c_sda` | 22 / 21 (ESP32), 5 / 4 (ESP8266) | I2C pins |
| `bluetooth.enabled` / `bthome` / `name` | true / true / "" | ESP32 only, see [bluetooth.md](bluetooth.md#settings) |
| `pins.<board>.display_reset` | GPIO4 (ESP32), none (ESP8266) | OLED reset pin for 7-pin modules |
| `sensor.temperature_offset` | 0.0 | °C added to the temperature ([sensors.md](sensors.md#temperature-offset)); settable from the app / `/offset` |
| `sensor.auto_calibration` | false | measure the offset automatically: nightly at `calibration_hour` (3, local) once the board knows the time, else every `calibration_interval_h` (24) hours (ESP32) |
| `time.offset_min` / `time.dst` | 0 / 0 | time zone (minutes from UTC, summer-time rule 0 none, 1 EU, 2 US); set by the app from the phone |
| `sensor.cooldown_min` | 20 | longest cooling time of a measurement |
| `display.enabled` | true | |
| `display.address` | 0x3C (60) | OLED I2C address |
| `display.page_s` | 5 | seconds per page |
| `display.contrast` | 255 | brightness 0–255 |
| `display.rotate` | false | true = turned 180°; also settable from the app or `/display` (then stored in `settings.json`) |
| `display.pages` | all | order and choice of `air`, `eco2`, `tvoc`, `temperature`, `humidity`, and on the ESP32 `dewpoint`, `sensor`, `system` |

The older firmware's `"devices": {"display": false}` still turns the display off.
Display choices sent with `/display` are stored in `settings.json` on the board
and override `display.pages` / `display.page_s`.
