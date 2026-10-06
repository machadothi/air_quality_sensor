#!/usr/bin/env python3
"""Screenshots from the real board: draws every display page with live sensor
readings on the ESP8266, reads the frame buffer back over USB and saves it
as PNG. Shows exactly what the OLED shows, including the real fonts.

    .venv/bin/python tools/screenshot.py [out_dir]     # default: preview/board/

It stops the running program (like any mpremote command) and restarts the
board when done. MQTT isn't connected while it runs, so the MQTT mark is
missing from the header. Needs mpremote and Pillow in the venv.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PORT = "/dev/ttyUSB0"
SCALE = 4

# Runs on the board. Prints one line per page: PAGE <name> <frame buffer as hex>.
BOARD_CODE = """
import time, network, ubinascii
import app, sensors, ui
cfg = app.load_config()
i2c = app.make_i2c(cfg)
display = ui.Display(i2c, cfg['display'])
air = sensors.AirSensor(i2c, cfg['sensor']['temperature_offset'])
class Net:
    wlan = network.WLAN(network.STA_IF)
    wifi_ok = wlan.isconnected()
    mqtt_ok = False
    def rssi(self): return self.wlan.status('rssi') if self.wifi_ok else 0
    def ip(self): return self.wlan.ifconfig()[0]
history = ui.History()
start = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), start) < 3000:
    air.update(); time.sleep_ms(50)
history.push(air)
for i, name in enumerate(display.pages):
    display.index = i
    display.refresh(air, Net(), history)
    print('PAGE', name, ubinascii.hexlify(display.oled.buffer).decode())
"""


def to_image(buffer):
    """SSD1306 buffer (MONO_VLSB, 128x64) -> PNG-ready image, white on black."""
    image = Image.new("1", (128 * SCALE, 64 * SCALE), 0)
    for y in range(64):
        for x in range(128):
            if buffer[(y >> 3) * 128 + x] >> (y & 7) & 1:
                for dy in range(SCALE - 1):
                    for dx in range(SCALE - 1):
                        image.putpixel((x * SCALE + dx, y * SCALE + dy), 1)
    return image


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "preview" / "board"
    out.mkdir(parents=True, exist_ok=True)
    mpremote = str(ROOT / ".venv" / "bin" / "mpremote")
    result = subprocess.run([mpremote, "connect", PORT, "exec", BOARD_CODE, "+", "reset"],
                            capture_output=True, text=True, timeout=120)
    pages = [line.split() for line in result.stdout.splitlines() if line.startswith("PAGE ")]
    if not pages:
        sys.exit("No pages received:\n" + result.stdout + result.stderr)
    for i, (_, name, hexdata) in enumerate(pages):
        path = out / f"{i + 1:02d}_{name}.png"
        to_image(bytes.fromhex(hexdata)).save(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
