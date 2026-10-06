#!/usr/bin/env python3
"""Render every display page to PNG on a PC, with made-up readings, to design
the screens without flashing the board.

    python3 tools/preview.py [out_dir]       # default: preview/ (git-ignored)

Writes one PNG per page, sheet.png with all of them (docs/display.png is a
copy) and slide.gif, the animation between pages.

Uses tools/sim/ (framebuf and ssd1306 stand-ins) and the real firmware/ui.py,
gfx.py and assets.py. Needs Pillow.
"""

import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools" / "sim"), str(ROOT / "firmware")]
os.chdir(ROOT / "firmware")   # gfx.py opens assets.bin from the current directory, as on the board

from PIL import Image  # noqa: E402

import ssd1306  # noqa: E402  (the stand-in)
import ui  # noqa: E402
import ui_more  # noqa: E402  (the ESP32's extra pages)

SCALE = 4


def to_image(fb):
    image = Image.new("RGB", (fb.width * SCALE + 8, fb.height * SCALE + 8), (20, 20, 20))
    for y in range(fb.height):
        for x in range(fb.width):
            if fb.pixel(x, y):
                for dy in range(SCALE - 1):
                    for dx in range(SCALE - 1):
                        image.putpixel((4 + x * SCALE + dx, 4 + y * SCALE + dy), (120, 200, 255))
    return image


class FakeAir:
    has_air = True
    has_climate = True
    valid = True
    temperature = 22.4
    humidity = 48.6
    eco2 = 812
    tvoc = 164
    aqi = 2
    validity = 0
    firmware = (5, 4, 6)
    r1_raw = 43478    # 2.4 MΩ
    r4_raw = 31276    # 39 kΩ
    comp_t = 22.4
    comp_rh = 48.6

    def warmup_left_s(self):
        return 104, 180


class FakeNet:
    wifi_ok = True
    mqtt_ok = True

    def rssi(self):
        return -61

    def ip(self):
        return "192.168.1.42"


class FakeApp:
    """What the system page needs from app.App."""
    ble = None

    def uptime_s(self):
        return 2 * 3600 + 13 * 60


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "preview"
    out.mkdir(exist_ok=True)
    frames = []
    ssd1306.on_show = lambda fb: frames.append(to_image(fb))

    ui_more.register(ui, FakeApp())
    cfg = {"address": 0x3C, "contrast": 255, "rotate": False,
           "pages": ["air", "eco2", "tvoc", "temperature", "humidity", "dewpoint", "sensor", "system"]}
    display = ui.Display(None, cfg)
    air, net, history = FakeAir(), FakeNet(), ui.History()
    for minute in range(ui.HISTORY_POINTS):
        air.eco2 = 700 + 250 * math.sin(minute / 9) + minute * 3
        air.tvoc = 120 + 80 * math.sin(minute / 6)
        air.temperature = 22 + 0.8 * math.sin(minute / 15)
        air.humidity = 48 + 3 * math.cos(minute / 11)
        history.push(air)

    def save(name):
        frames.clear()
        display.refresh(air, net, history)
        frames[-1].save(out / f"{name}.png")

    display.splash("Connecting to Wi-Fi", 0.4)
    frames[-1].save(out / "00_splash.png")
    for i, name in enumerate(cfg["pages"]):
        display.index = i
        save(f"{i + 1:02d}_{name}")

    display.index = 0
    air.aqi, air.eco2, air.tvoc = 4, 1630, 1119
    save("10_air_poor")
    air.valid = False
    save("11_air_warming_up")
    net.wifi_ok = net.mqtt_ok = False
    display.index = 7
    save("12_system_offline")
    air.has_air = air.valid = False
    display.index = 0
    save("13_air_no_sensor")
    air.has_air = True

    # All pages on one sheet, for the README.
    pages = sorted(out.glob("[0-9]*.png"))
    images = [Image.open(page) for page in pages]
    w, h = images[0].size
    sheet = Image.new("RGB", (3 * w + 16, ((len(images) + 2) // 3) * (h + 8) - 8), (0, 0, 0))
    for i, image in enumerate(images):
        sheet.paste(image, ((i % 3) * (w + 8), (i // 3) * (h + 8)))
    sheet.save(out / "sheet.png")

    # The slide from one page to the next, as an animated GIF.
    air.valid, net.wifi_ok, net.mqtt_ok = True, True, True
    display.index = 0
    display.refresh(air, net, history)
    frames.clear()
    display.next_page(air, net, history)
    frames[0].save(out / "slide.gif", save_all=True, append_images=frames[1:] + [frames[-1]] * 8,
                   duration=45, loop=0)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
