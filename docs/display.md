# Display, and how to build a UI like it

The OLED is a 128×64, one-bit SSD1306 driven over I2C. With only MicroPython's
built-in 8×8 font, the old firmware showed five lines of small text. This
version uses proportional fonts, icons, charts and animation, and it does that
in about 10 KB of RAM. This page describes the result, then shows **how to
build such a UI**, step by step, so you can change it or reuse the approach.

- [The pages](#the-pages)
- [Choosing the pages](#choosing-the-pages)
- [How it works](#how-it-works)
  - [1. Design on the PC, not on the board](#1-design-on-the-pc-not-on-the-board)
  - [2. Fonts: render TrueType to bitmaps with Pillow](#2-fonts-render-truetype-to-bitmaps-with-pillow)
  - [3. Icons: ASCII art](#3-icons-ascii-art)
  - [4. Drawing text and icons with framebuf](#4-drawing-text-and-icons-with-framebuf)
  - [5. Layout](#5-layout)
  - [6. Charts](#6-charts)
  - [7. Animation: sliding pages](#7-animation-sliding-pages)
  - [8. Preview without the board](#8-preview-without-the-board)
  - [9. Screenshots from the board](#9-screenshots-from-the-board)
- [Recipes](#recipes)

![All pages](images/display.png)

## The pages

| Page | Shows |
|---|---|
| `air` | rating (Excellent … Unhealthy) and the 1–5 gauge, with eCO2 and TVOC below. "Poor" or worse is shown inverted (white box) to stand out. During warm-up: a progress bar and the time left. |
| `eco2` | eCO2 in ppm, big, with the last hour as a chart |
| `tvoc` | TVOC in ppb + chart |
| `temperature` | °C + chart |
| `humidity` | % + chart |
| `dewpoint` | dew point, big; absolute humidity and comfort below (ESP32) |
| `sensor` | ENS160 firmware and state, raw resistances R1/R4, the compensation it uses (ESP32) |
| `system` | Wi-Fi signal, IP, links (MQTT, Bluetooth), uptime (ESP32) |
| `clock` | local time, big; weekday and date (ESP32) |
| `weather` | Open-Meteo: temperature, condition (icon in the header), today's high/low; the title is the place (ESP32) |

**Internet-dependent pages** (weather) are shown only while the board is
*online*: Wi-Fi up and its latest internet request (time sync, weather) worked
(`App.online()`). Offline they're skipped, like CO2/TVOC during warm-up. A
future internet feature adds its condition to `ui._NEEDS` the same way
(`ui_more.register`). The **clock** page needs the internet too, unless the
time was set from the phone or by hand in the app (`Clock.trusted()`).

**Header icons** left of Wi-Fi/MQTT come from `ui.STATUS_ICONS`, a list of
functions returning an icon or `None`. On the ESP32 it has one: the update
icon (arrow into a tray) while a firmware update waits for an answer in the
app ([updates.md](updates.md)).

The last three are in `firmware/ui_more.py`, which only the ESP32 loads: the
ESP8266 has no RAM to spare for them.

Every page has the same frame:

```
+--------------------------------+
|[icon] Title          [mq][wifi]|  header, y 0-12: arrows = MQTT connected, Wi-Fi or crossed Wi-Fi
|. . . . . . . . . . . . . . . . |  dotted separator, y 14
|        1021 ppm                |  value: 23 px digits + unit, y 18-40
|   ___/\__/~~\___               |  last hour, y 45-58
|            - . . . .           |  page dots, y 62
+--------------------------------+
```

- **Page changes** slide the next page in from the right (about 0.6 s).
- **Live values:** the current page is redrawn every second.
- **Warm-up:** the CO2 and TVOC pages are skipped until the ENS160 has valid
  data, so you don't see the same "Warming up" screen three times.

## Choosing the pages

Which pages appear, their order and the time per page can be set in three ways:
- **From the BLE Sensor phone app** (ESP32, over Bluetooth): Settings → Display;
  see [bluetooth.md](bluetooth.md).
- **Over MQTT,** without touching the board:
  ```sh
  mosquitto_pub ... -t esp/<client_id>/request -m '/display {"pages": ["air", "temperature", "humidity"], "page_s": 8}'
  ```
  It takes effect at once. The board stores it in `settings.json` and it
  survives restarts. Plain `/display` returns the current choice; see
  [communication.md](communication.md#requests).
- **In `config.json`:** `display.pages` and `display.page_s`.

`settings.json` wins over `config.json`. Delete it from the board
(`mpremote fs rm :settings.json`) to go back to `config.json`.

## How it works

### 1. Design on the PC, not on the board

The drawing code (`ui.py`, `gfx.py`) only uses `framebuf`, so it runs
unchanged on a PC once there's a stand-in for `framebuf`. `tools/sim/` has
one in plain Python (about 100 lines). That lets you iterate in seconds
instead of deploying to the board every time.

```
tools/make_assets.py  ──►  firmware/assets.py + assets.bin      (fonts, icons)
tools/preview.py      ──►  preview/*.png, sheet.png, slide.gif   (screens, made-up data)
tools/screenshot.py   ──►  preview/board/*.png                   (screens from the real board)
```

### 2. Fonts: render TrueType to bitmaps with Pillow

MicroPython can't render TrueType, and a 1-bit screen wants crisp pixels
anyway. So `tools/make_assets.py` renders each character once on the PC with
**Pillow** and stores the pixels:

```python
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
image = Image.new("1", (width, height), 0)          # 1-bit image
draw = ImageDraw.Draw(image)
draw.fontmode = "1"                                  # no anti-aliasing: pixels are on or off
draw.text((-left, -top), "7", font=font, fill=1)
```

The important details:
- **`fontmode = "1"`** turns anti-aliasing off. Grey edges would turn into
  random pixels on a one-bit screen.
- **One shared baseline.** The top and bottom over *all* characters of a font
  are measured first (`getbbox`), and every glyph is cut to that height. So
  "7" and "g" line up when drawn at the same y.
- **Only the characters you need.** The big font only has `0123456789.-`; the
  others have letters and a few symbols (`°`, `%`).
- **Packed MONO_HLSB.** Each glyph row becomes bytes, 8 pixels per byte, most
  significant bit first. That is one of `framebuf`'s formats, so a glyph can be
  wrapped in a `FrameBuffer` and blitted without conversion.

The three fonts:

| Name | Source | Height | Used for |
|---|---|---|---|
| `BIG` | DejaVu Sans Bold 32 px | 23 px | values |
| `MID` | DejaVu Sans Bold 15 px | 14 px | units, rating, messages |
| `SMALL` | DejaVu Sans Bold 10 px | 10 px | titles, small text |

Bold reads much better than regular at these sizes on an OLED.

### 3. Icons: ASCII art

Icons are drawn right in `make_assets.py`, `#` for a lit pixel:

```python
"drop": """
    .....##.....
    .....##.....
    ....####....
    ....####....
    ...######...
    ..########..
    ..########..
    .#.########.
    .#.########.
    .##.#######.
    ..########..
    ....####....
""",
```

At 12×12 pixels, drawing pixel by pixel beats scaling down any image. The
dots inside the drop are a highlight, which makes it read as round.

### 4. Drawing text and icons with framebuf

The generator writes two files:
- **`assets.bin`:** all glyph bitmaps, back to back (3.6 KB);
- **`assets.py`:** per font its height, characters, widths and byte offsets
  into the `.bin`.

`gfx.py` draws a string like this:

```python
def text(fb, font, s, x, y, c=1):
    height, chars, widths, offsets = font
    for ch in s:
        i = chars.find(ch)
        if i >= 0:
            w = widths[i]
            glyph = _load(offset_of(i), w, height)    # read the glyph from flash into a small buffer
            fb.blit(glyph, x, y, 0)                   # key 0: unlit glyph pixels are transparent
            x += w
    return x
```

- **Transparency.** `blit(..., key=0)` skips the glyph's unlit pixels, so text
  can be drawn over anything.
- **Black on white** (the inverted "Poor" box) uses blit's **palette**: a 2×1
  frame buffer that maps source color 1 → 0 and 0 → 1, with key 1:
  `fb.blit(glyph, x, y, 1, palette)`.
- **Bitmaps stay in flash.** `_load()` seeks in `assets.bin` and reads one
  glyph (at most 69 bytes) into a reused buffer. Kept in RAM, the fonts would
  take 10 KB, a third of what the ESP8266 has.
- **Centering.** `text_width()` sums the widths, so `text_center` and
  `text_right` are one line each.

### 5. Layout

All positions are constants at the top of `ui.py` (`VALUE_Y`, `CHART_Y`, …),
and each page is one function:

```python
def page_air(fb, air, net, history):
    ...
_PAGES = {
    "air": ("Air quality", assets.ICON_LEAF, page_air),
    "eco2": ("CO2", assets.ICON_CLOUD, _chart_page("eco2", 0, "ppm", 100, True)),
    ...
}
```

`_chart_page` builds the four "big number + chart" pages from parameters: the
reading, decimals, unit, minimum chart span, and whether the ENS160 must be
ready. The header, separator and page dots are drawn around every page by
`Display._draw()`.

Rules that make a 128×64 screen look good:
- **One message per page,** big. Small text only for secondary details.
- **Group value and unit and center them as one.** The unit sits on the
  value's baseline, in the smaller font.
- **Dotted lines and patterns instead of grey.** A dotted separator or a
  sparse fill under a chart reads as "lighter" on a one-bit screen.
- **Invert for alerts.** A white box is the strongest emphasis available.

### 6. Charts

`gfx.sparkline()` draws the last hour (60 points, one a minute) across the
full width:
- **Minimum span.** The scale fits the data but never spans less than a
  minimum (e.g. 1 °C, 100 ppm). Otherwise a steady 22.0 → 22.1 °C would fill
  the whole height and look like a storm.
- **Gaps** (`None`: no data yet, or warm-up) break the line.
- **Fill.** Below the line, every third column gets every second pixel,
  giving a light "area chart" texture.
- **Compact history.** `ui.History` keeps the points in `array('h')` (16-bit),
  scaled (temperature × 10), with −32768 meaning "no data".

### 7. Animation: sliding pages

A slide needs the old and the new page at once. Copying both into a third
buffer for every frame would cost RAM, so `next_page()` uses `framebuf.scroll`:

```python
self._draw(...)                         # new page -> back buffer
for pos in (10, 26, 46, 68, 88, 104, 116, 123, 127, 128):
    oled.scroll(shown - pos, 0)         # the screen's content moves left...
    oled.blit(self.back, 128 - pos, 0)  # ...and the new page is drawn into the gap at the right
    oled.show()
    shown = pos
```

- **Two buffers only:** the screen's and one back buffer.
- **Easing.** The steps start large and end small (ease-out), so the page
  decelerates into place. Even steps look mechanical.
- **Speed.** A frame is ~60 ms (the I2C transfer dominates), 10 frames ≈ 0.6 s.
  The CPU runs at 160 MHz for this (`machine.freq` in `app.py`).

### 8. Preview without the board

```sh
.venv/bin/python tools/preview.py      # -> preview/
```

It runs the **real** `ui.py`, `gfx.py` and `assets` against:
- `tools/sim/framebuf.py`, `framebuf` in plain Python (pixel, lines,
  rectangles, `blit` with key and palette, `scroll`);
- `tools/sim/ssd1306.py`, whose `show()` hands each frame to the preview
  script;
- made-up readings and a sine-wave history.

Output: one PNG per page and state (poor air, warming up, offline, no
sensor), `sheet.png` with all of them (copied to `docs/images/display.png`),
and `slide.gif`, the page transition frame by frame.

### 9. Screenshots from the board

```sh
.venv/bin/python tools/screenshot.py   # -> preview/board/
```

This sends a short program to the board (via `mpremote exec`). It draws each
page with **live** sensor data, prints the frame buffer as hex, and the PC
turns that into PNGs. Then the board is restarted. Use it to confirm the board
shows what the preview promised: fonts, real values, real network state.

## Recipes

**Change a font size or add a character.** Edit `FONTS` in
`tools/make_assets.py`, run it, deploy:

```sh
.venv/bin/python tools/make_assets.py && .venv/bin/python tools/preview.py && tools/deploy.sh
```

A character missing from a font is silently skipped when drawn, so check the
preview.

**Add an icon.** Add ASCII art to `ICONS` (rows of equal length); it becomes
`assets.ICON_<NAME>`.

**Add a page.** Write `def page_x(fb, air, net, history)` in `ui.py`, drawing
below y = 15. Add it to `_PAGES`, and add its name to `display.pages` (and to
the app's list of pages).

**Upside down / dimmer / brighter.** In the app: Settings → Display → Upside
down (ESP32), or `/display {"rotate": true}` over MQTT; in `config.json`:
`display.rotate`, `display.contrast`
(0–255; 255 is the brightest the SSD1306 does) in `config.json`.

**Burn-in.** OLEDs age where pixels are lit most. Rotating pages helps; lower
contrast helps more.
