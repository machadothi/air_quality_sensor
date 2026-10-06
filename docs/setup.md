# Setup

From an empty board to a running air monitor.

## Downloads

| What | Where | Used for |
|---|---|---|
| MicroPython 1.24.1 for ESP8266 | <https://micropython.org/download/ESP8266_GENERIC/>, file `ESP8266_GENERIC-20241129-v1.24.1.bin` | the board's firmware (interpreter + frozen libraries) |
| Python 3.10+ | your distribution (`sudo apt install python3 python3-venv`) | the PC tools |
| mpremote | `requirements.txt` (PyPI) | copy files, REPL, reset |
| mpy-cross **1.24.1** | `requirements.txt`, pinned `1.24.1.post3` | compile to `.mpy`; must match the firmware version |
| esptool | `requirements.txt` | flash MicroPython |
| Pillow | `requirements.txt` | generate fonts/icons, previews, screenshots |
| DejaVu fonts | `sudo apt install fonts-dejavu-core` | only for `tools/make_assets.py` |
| USB-serial driver | in Linux already (CH340 / CP210x) | the board appears as `/dev/ttyUSB0` |

If you change the MicroPython version, use the matching mpy-cross
(`pip install 'mpy-cross==<version>.*'`). A mismatch shows up as
`ValueError: incompatible .mpy file` at boot.

## 1. PC tools

```sh
cd ~/git/air_quality_sensor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout $USER     # access to /dev/ttyUSB0; log out and in once
```

## 2. MicroPython (new or wiped board only)

```sh
.venv/bin/esptool.py --port /dev/ttyUSB0 erase_flash
.venv/bin/esptool.py --port /dev/ttyUSB0 --baud 460800 write_flash --flash_size=detect 0 ESP8266_GENERIC-20241129-v1.24.1.bin
.venv/bin/mpremote connect /dev/ttyUSB0 exec "import sys; print(sys.version)"    # check
```

`erase_flash` also erases the files on the board, including `config.json`.

## 3. Configuration

```sh
cp firmware/config.example.json firmware/config.json
```

Edit `firmware/config.json`: Wi-Fi name and password, MQTT broker IP, user and
password. The file is git-ignored, so the passwords don't end up in git. All
settings are described in [communication.md](communication.md#configjson).

## 4. Deploy

```sh
tools/deploy.sh --config     # first time: code + config.json
tools/deploy.sh              # later: code only, the board keeps its config.json
```

What `deploy.sh` does:
1. Compiles each module in `firmware/` to `build/<module>.mpy` with mpy-cross.
2. Stops the running program (mpremote sends Ctrl+C).
3. Deletes stale `.py` copies of compiled modules from the board; MicroPython
   would import a `.py` before the `.mpy`.
4. Uploads the `.mpy` files, `assets.bin`, `boot.py`, `main.py` (and `config.json`).
5. Resets the board.

Other boards or ports: `PORT=/dev/ttyUSB1 tools/deploy.sh`.

## 5. Check it runs

```sh
.venv/bin/mpremote connect /dev/ttyUSB0 repl
```

After a reset you should see:

```
AHT21 found
ENS160 found
Wi-Fi: connecting to <your network>
Wi-Fi: connected, 192.168.1.42
MQTT: connecting to 192.168.1.10
MQTT: connected, requests on esp/air-monitor/request
Running
```

Ctrl+C stops the program (back to `>>>`), Ctrl+] leaves mpremote. To start
it again: `import app; app.run()` or `.venv/bin/mpremote connect /dev/ttyUSB0 reset`.

## Everyday commands

```sh
tools/deploy.sh                                       # after changing code
.venv/bin/mpremote connect /dev/ttyUSB0 fs ls         # files on the board
.venv/bin/mpremote connect /dev/ttyUSB0 fs cat :config.json
.venv/bin/python tools/preview.py                     # screens on the PC -> preview/
.venv/bin/python tools/screenshot.py                  # screens from the board -> preview/board/
.venv/bin/python tools/make_assets.py                 # after changing fonts/icons
```
