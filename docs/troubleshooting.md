# Troubleshooting

**Watch the log first:** `.venv/bin/mpremote connect /dev/ttyUSB0 repl`, then
reset the board (`Ctrl+D` in the REPL, or the reset button). Ctrl+] leaves.

| Symptom | Cause and fix |
|---|---|
| `mpremote` shows garbage or "could not enter raw repl" | the program is busy, or the board just reset (its boot message is at 74880 baud, so it looks like garbage). Run the command again. |
| `Permission denied: /dev/ttyUSB0` | `sudo usermod -aG dialout $USER`, then log out and in |
| `ValueError: incompatible .mpy file` | mpy-cross version ≠ firmware version; see [setup.md](setup.md#downloads) |
| `MemoryError` at start | a `.py` copy of a module is being compiled on the board, or new code grew too big. `tools/deploy.sh` removes stale `.py` files; see [architecture.md](architecture.md#ram-budget) |
| Display says **No sensor** | wiring; check the I2C scan in [hardware.md](hardware.md#wiring) |
| Display blank, log says `Display not found` | OLED wiring or address; try `"display": {"address": 61}` (0x3D) |
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
