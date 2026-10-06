# The OLED screens: one reading per page, sliding from one page to the next.
#
#   +--------------------------------+
#   |[icon] Title           [mq][wifi]|  header, y 0-12
#   |. . . . . . . . . . . . . . . . |  y 14
#   |        1021 ppm                |  value, y 18-40
#   |   ___/\__/~~\___               |  last hour, y 45-58
#   |            - . . . .           |  page dots, y 62
#   +--------------------------------+
#
# Pages draw into a back buffer; refresh() copies it to the screen, next_page()
# slides it in. Layout constants are pixel positions on the 128x64 screen.
import framebuf
from array import array

import ssd1306

import assets
import gfx

W = 128
H = 64
VALUE_Y = 18
CHART_Y = 45
CHART_H = 14
DOTS_Y = 62

# Slide positions per frame: fast start, soft landing.
SLIDE = (10, 26, 46, 68, 88, 104, 116, 123, 127, 128)

AQI_NAMES = ("", "Excellent", "Good", "Moderate", "Poor", "Unhealthy")

# History: one point a minute, one hour per chart.
HISTORY_POINTS = 60
# Stored as 16-bit integers: reading x scale.
HISTORY_SCALE = {"eco2": 1, "tvoc": 1, "temperature": 10, "humidity": 10}
_GAP = -32768


class History:
    """The last hour of each reading, for the charts: a 16-bit array per
    reading (not a list of floats, to save RAM); _GAP marks no data."""

    def __init__(self):
        self.values = {key: array("h", [_GAP] * HISTORY_POINTS) for key in HISTORY_SCALE}

    def push(self, air):
        valid_air = air.valid
        for key, series in self.values.items():
            value = getattr(air, key)
            if value is None or (key in ("eco2", "tvoc") and not valid_air):
                stored = _GAP
            else:
                stored = max(-32767, min(32767, int(value * HISTORY_SCALE[key] + 0.5)))
            for i in range(HISTORY_POINTS - 1):
                series[i] = series[i + 1]
            series[-1] = stored

    def series(self, key):
        """The values of one reading, oldest first, None for gaps."""
        scale = HISTORY_SCALE[key]
        return [None if v == _GAP else v / scale for v in self.values[key]]


def _fmt(value, decimals):
    if value is None:
        return "--"
    return "%.*f" % (decimals, value) if decimals else str(int(value + 0.5))


class Display:
    def __init__(self, i2c, cfg):
        self.oled = ssd1306.SSD1306_I2C(W, H, i2c, addr=cfg["address"])
        self.oled.contrast(cfg["contrast"])
        # The driver's rotate(True) is the normal orientation (what its init sets).
        self.oled.rotate(not cfg["rotate"])
        self.back = framebuf.FrameBuffer(bytearray(W * H // 8), W, H, framebuf.MONO_VLSB)
        self.set_pages(cfg["pages"])

    def set_pages(self, pages):
        """Show these pages, in this order (unknown names are ignored)."""
        self.pages = [name for name in pages if name in _PAGES] or ["air"]
        self.index = 0

    # --- public ---------------------------------------------------------------

    def splash(self, status, progress=None, title="Air Monitor"):
        """Full screen: icon, title, a status line and, if given, a progress
        bar (0..1). The start screen, and the error screen before a restart."""
        fb = self.back
        fb.fill(0)
        gfx.icon(fb, assets.ICON_LEAF, 58, 4)
        gfx.text_center(fb, assets.MID, title, 20)
        gfx.text_center(fb, assets.SMALL, status, 39)
        if progress is not None:
            fb.rect(14, 54, 100, 6, 1)
            fb.fill_rect(16, 56, int(96 * min(1, max(0, progress))), 2, 1)
        self._present()

    def refresh(self, air, net, history):
        """Redraw the current page with fresh values."""
        self._draw(air, net, history)
        self._present()

    def next_page(self, air, net, history):
        """Slide the next page in from the right. Pages without data yet (CO2 and
        TVOC while the sensor warms up or is missing) are skipped."""
        n = len(self.pages)
        for step in range(1, n + 1):
            index = (self.index + step) % n
            if self.pages[index] not in _NEED_VALID_AIR or air.valid:
                break
        if index == self.index:
            self.refresh(air, net, history)
            return
        self.index = index
        self._draw(air, net, history)
        oled = self.oled
        shown = 0
        for pos in SLIDE:
            oled.scroll(shown - pos, 0)       # old page moves left...
            oled.blit(self.back, W - pos, 0)  # ...new page follows it in
            oled.show()
            shown = pos

    # --- drawing --------------------------------------------------------------

    def _present(self):
        self.oled.blit(self.back, 0, 0)
        self.oled.show()

    def _draw(self, air, net, history):
        fb = self.back
        fb.fill(0)
        name = self.pages[self.index]
        title, icon, draw = _PAGES[name]
        self._header(title, icon, net)
        draw(fb, air, net, history)
        self._dots()

    def _header(self, title, icon, net):
        fb = self.back
        gfx.icon(fb, icon, 0, 0)
        gfx.text(fb, assets.SMALL, title, 16, 1)
        gfx.icon(fb, assets.ICON_WIFI if net.wifi_ok else assets.ICON_WIFI_OFF, 117, 2)
        if net.mqtt_ok:
            gfx.icon(fb, assets.ICON_LINK, 108, 2)
        gfx.dotted_hline(fb, 0, 14, W)

    def _dots(self):
        n = len(self.pages)
        if n < 2:
            return
        x = (W - (n * 6 - 2)) // 2
        for i in range(n):
            if i == self.index:
                self.back.fill_rect(x, DOTS_Y, 4, 2, 1)
            else:
                self.back.fill_rect(x + 1, DOTS_Y, 2, 2, 1)
            x += 6


# --- pages ----------------------------------------------------------------------
# Each draws everything below the header: draw(fb, air, net, history).


def _big_value(fb, value, decimals, unit):
    """Big number with its unit, centered as a group."""
    s = _fmt(value, decimals)
    unit_w = gfx.text_width(assets.MID, unit)
    total = gfx.text_width(assets.BIG, s) + 3 + unit_w
    x = gfx.text(fb, assets.BIG, s, (W - total) // 2, VALUE_Y)
    gfx.text(fb, assets.MID, unit, x + 3, VALUE_Y + 10)


def _warming_up(fb, air):
    """Shown instead of air readings while the ENS160 heats up (invalid data)."""
    left, total = air.warmup_left_s()
    gfx.text_center(fb, assets.MID, "Warming up", VALUE_Y)
    fb.rect(14, 37, 100, 7, 1)
    done = 1 - left / total if total else 0
    fb.fill_rect(16, 39, int(96 * done), 3, 1)
    gfx.text_center(fb, assets.SMALL, "about %d min left" % ((left + 59) // 60) if left else "almost ready", 48)


def _no_sensor(fb):
    gfx.text_center(fb, assets.MID, "No sensor", VALUE_Y + 2)
    gfx.text_center(fb, assets.SMALL, "check the I2C wiring", 40)


def page_air(fb, air, net, history):
    if not air.has_air:
        _no_sensor(fb)
        return
    if not air.valid:
        _warming_up(fb, air)
        return
    aqi = air.aqi or 0
    name = AQI_NAMES[aqi] if 0 < aqi < len(AQI_NAMES) else "--"
    if aqi >= 4:   # poor or worse: white box, black text
        width = gfx.text_width(assets.MID, name) + 12
        fb.fill_rect((W - width) // 2, VALUE_Y - 2, width, 17, 1)
        gfx.text_center(fb, assets.MID, name, VALUE_Y, 0)
    else:
        gfx.text_center(fb, assets.MID, name, VALUE_Y)
    # Five segments, the current one filled, with a pointer above it.
    for i in range(5):
        x = i * 26
        if i + 1 == aqi:
            fb.fill_rect(x, 39, 24, 6, 1)
            for row in range(3):   # pointer
                fb.hline(x + 12 - row, 35 + row, row * 2 + 1, 1)
        else:
            fb.rect(x, 39, 24, 6, 1)
    gfx.text(fb, assets.SMALL, "CO2 " + _fmt(air.eco2, 0), 0, 49)
    gfx.text_right(fb, assets.SMALL, "VOC " + _fmt(air.tvoc, 0), W, 49)


def _chart_page(key, decimals, unit, min_span, needs_valid_air):
    def draw(fb, air, net, history):
        if not (air.has_air if needs_valid_air else air.has_climate):
            _no_sensor(fb)
            return
        if needs_valid_air and not air.valid:
            _warming_up(fb, air)
            return
        _big_value(fb, getattr(air, key), decimals, unit)
        gfx.sparkline(fb, history.series(key), 0, CHART_Y, W, CHART_H, min_span)
    return draw


_NEED_VALID_AIR = ("eco2", "tvoc")

# name: (title, icon, draw). display.pages picks and orders them; the default
# order is app.PAGE_NAMES. (The network page was dropped to save RAM: the
# header shows Wi-Fi/MQTT, and the /status request gives IP and signal.)
_PAGES = {
    "air": ("Air quality", assets.ICON_LEAF, page_air),
    "eco2": ("CO2", assets.ICON_CLOUD, _chart_page("eco2", 0, "ppm", 100, True)),
    "tvoc": ("TVOC", assets.ICON_FLASK, _chart_page("tvoc", 0, "ppb", 50, True)),
    "temperature": ("Temperature", assets.ICON_THERMO, _chart_page("temperature", 1, "°C", 1.0, False)),
    "humidity": ("Humidity", assets.ICON_DROP, _chart_page("humidity", 1, "%", 4.0, False)),
}
