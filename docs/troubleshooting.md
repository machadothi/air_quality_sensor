# Troubleshooting

**Watch the log first:** `.venv/bin/mpremote connect /dev/ttyUSB0 repl`, then
reset the board (`Ctrl+D` in the REPL, or the reset button). Ctrl+] leaves.

| Symptom | Cause and fix |
|---|---|
| `mpremote` shows garbage or "could not enter raw repl" | the program is busy, or the board just reset (its boot message is at 74880 baud, so it looks like garbage). Run the command again. |
| `Permission denied: /dev/ttyUSB0` | `sudo usermod -aG dialout $USER`, then log out and in |
| `ValueError: incompatible .mpy file` | mpy-cross version ≠ firmware version; see [setup.md](setup.md#downloads) |
| `MemoryError` at start | a `.py` copy of a module is being compiled on the board, or new code grew too big. `tools/deploy.sh` removes stale `.py` files; see [architecture.md](architecture.md#ram-budget) |
| Display says **No sensor** | wiring; check the I2C scan in [hardware.md](hardware.md#checking-the-wiring) |
| Display blank, log says `Display not found` | OLED wiring or address; try `"display": {"address": 61}` (0x3D). A 7-pin 2.42" module also needs RES on GPIO4, DC and CS on GND, and I2C mode set on its back; see [hardware.md](hardware.md#wiring-esp32) |
| Display upside down | `"display": {"rotate": true}` |
| **Warming up** for more than 3 min | a new ENS160 has a one-time 1-hour start-up, then settles for a day |
| Temperature 1–3 °C too high | ENS160 heater; set `sensor.temperature_offset`, see [sensors.md](sensors.md#temperature-offset) |
| `MQTT: failed (5)` | broker refused: wrong user/password |
| `MQTT: failed ([Errno 113] EHOSTUNREACH)` | wrong broker IP, or the broker is down; retries back off up to 2 min |
| Wi-Fi never connects | 2.4 GHz only; check `wifi.ssid`/`password`; `/status` shows the signal (below −80 dBm is weak) |
| Display ignores `display.pages` in config.json | a choice sent with `/display` is in `settings.json` and wins; delete it: `mpremote fs rm :settings.json` |
| Tracebacks without line numbers | the code is compiled with `-O3` to save RAM; remove `-O3` in `tools/deploy.sh` while debugging |
| Board restarts by itself | the log says why: `Watchdog: main loop stuck` or a traceback before `Error ... restarting` |
| Home Assistant shows duplicates | YAML sensors and discovery both active; remove the YAML ones |

## Bluetooth (ESP32)

| Symptom | Cause and fix |
|---|---|
| The BLE Sensor app doesn't list the board | the log should say `Bluetooth: advertising as Air-Monitor-XXXX`; check `"bluetooth": {"enabled": true}`. Phones cache: pull to refresh the scan. Only one phone can be connected. |
| The app connects but shows only temperature/humidity | the air sensor is warming up (3 min) or missing; the Air card says which |
| Display or name change from the app didn't stick | the value was out of range (no pages, time outside 1–60 s, name over 20 bytes); the board keeps the old one, see [bluetooth.md](bluetooth.md#limits) |
| Temperature/humidity twice in Home Assistant | MQTT and BTHome both report them; ignore one, or set `"bthome": false` |

## ESP32 won't flash or boot

These all happened while setting up the ESP32; the fixes are what worked.

| Symptom | Cause and fix |
|---|---|
| esptool: "No serial data received" | the board didn't enter download mode by itself: hold **BOOT**, tap **EN**, release BOOT, run esptool again |
| The board keeps dropping off USB, or prints garbage after a clean `ets Jul 29 2019` line | the 3.3 V supply sags at start-up. Disconnect everything from the pins, and power the 2.42" OLED from **5 V**, not 3V3 (see [hardware.md](hardware.md#wiring-esp32)) |
| Pressing EN disconnects USB | same cause: the reset spike pulls the supply down far enough to reset the USB chip too |
| esptool connects but every write stops at the first block ("No more data to read") | seen on one particular board even with nothing attached; another ESP32 flashed at once. Try another board. |
| mpremote: "could not enter raw repl" right after plugging in | the board is still starting; wait 2–3 s and retry |

## Useful REPL snippets

```python
import gc; gc.collect(); gc.mem_free()                  # free RAM
import os; os.listdir()                                 # files
import network; network.WLAN(network.STA_IF).ifconfig() # IP
import machine; machine.reset()                         # restart
```

## Starting over

```sh
.venv/bin/esptool.py --port /dev/ttyUSB0 erase_flash    # wipes firmware and files
```

Then follow [setup.md](setup.md) from step 2.
