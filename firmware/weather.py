# Weather from Open-Meteo (https://open-meteo.com; open source, no API key,
# built on the national weather services' models), ESP32 only.
#
# The place: found automatically from the board's internet address (ip-api.com,
# city level) when none is set, or set by name from the app, which Open-Meteo's
# geocoding turns into coordinates. Stored in settings.json. The forecast is
# fetched every 30 min while the board is online, and counts as stale after 3 h.
#
# Plain HTTP on purpose: weather is public, and with Wi-Fi and Bluetooth running
# the ESP32 has too little internal RAM left for a TLS (HTTPS) connection.
#
# An internet-dependent feature: see App.online(). Its display page is skipped
# while the board is offline or has no fresh data.
import time

from micropython import const

_FORECAST = ("http://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
             "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
             "wind_speed_10m,is_day&daily=temperature_2m_max,temperature_2m_min,"
             "precipitation_probability_max&timezone=auto&forecast_days=1&wind_speed_unit=ms")
_GEOCODE = "http://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&format=json"
_LOCATE = "http://ip-api.com/json/?fields=status,message,city,country,lat,lon"   # free, non-commercial use
_EVERY_MS = const(30 * 60 * 1000)
_RETRY_MS = const(5 * 60 * 1000)
_STALE_MS = const(3 * 3600 * 1000)

# WMO weather codes (Open-Meteo docs) -> (short text, icon)
_KINDS = (
    ((0,), "Clear", "sun"),
    ((1, 2), "Partly cloudy", "partly"),
    ((3,), "Overcast", "cloud"),
    ((45, 48), "Fog", "fog"),
    ((51, 53, 55, 56, 57), "Drizzle", "rain"),
    ((61, 63, 65, 66, 67, 80, 81, 82), "Rain", "rain"),
    ((71, 73, 75, 77, 85, 86), "Snow", "snow"),
    ((95, 96, 99), "Thunderstorm", "thunder"),
)


def describe(code):
    """(text, icon name) for a WMO weather code."""
    for codes, text, icon in _KINDS:
        if code in codes:
            return text, icon
    return "--", "cloud"


def _quote(text):
    """URL-encode a place name (letters and digits stay, the rest as %XX)."""
    out = ""
    for byte in text.encode():
        c = chr(byte)
        out += c if c.isalpha() and byte < 128 or c.isdigit() else "%%%02X" % byte
    return out


class Weather:
    def __init__(self, app):
        self.app = app
        self.now = None           # dict of the latest data, see _fetch
        self.fetched = None       # ticks of the last good fetch
        self.error = None
        self._next = time.ticks_ms()
        self._place_request = None

    @property
    def cfg(self):
        return self.app.cfg["weather"]

    def fresh(self):
        return self.now is not None and time.ticks_diff(time.ticks_ms(), self.fetched) < _STALE_MS

    def set_place(self, name):
        """Look the place up (on the next poll, which may block ~1 s).
        "" or "auto": find it from the board's internet address."""
        self._place_request = name.strip() or "auto"

    def refresh(self):
        self._next = time.ticks_ms()

    def poll(self):
        if not self.cfg["enabled"] or not self.app.net.wifi_ok:
            return
        if self._place_request is None and self.cfg["latitude"] is None:
            self._place_request = "auto"   # no place yet: find one
        if self._place_request:
            name, self._place_request = self._place_request, None
            if name.lower() == "auto":
                self._locate()
            else:
                self._geocode(name)
        if self.cfg["latitude"] is None or time.ticks_diff(time.ticks_ms(), self._next) < 0:
            return
        self._fetch()

    def _get(self, url):
        import gc
        import requests
        gc.collect()
        r = requests.get(url, timeout=10)
        try:
            if r.status_code != 200:
                raise OSError("HTTP %d" % r.status_code)
            return r.json()
        finally:
            r.close()

    def _locate(self):
        """The board's location from its public IP address (city level)."""
        try:
            found = self._get(_LOCATE)
        except Exception as e:
            self.app.internet_result(False)
            self.error = "location lookup failed: %s" % e
            print("Weather:", self.error)
            return
        if found.get("status") != "success":
            self.error = "location unknown: %s" % found.get("message")
            print("Weather:", self.error)
            return
        self._use_place(found["city"], found["lat"], found["lon"], found.get("country", ""), auto=True)

    def _use_place(self, name, latitude, longitude, country, auto):
        cfg = self.cfg
        cfg["latitude"], cfg["longitude"], cfg["place"], cfg["auto_place"] = latitude, longitude, name, auto
        self.error = None
        self.app.save_settings()
        print("Weather: place %s, %s (%.2f, %.2f)%s" % (name, country, latitude, longitude, " found automatically" if auto else ""))
        self.refresh()
        self.app.internet_result(True)

    def _geocode(self, name):
        try:
            found = self._get(_GEOCODE % _quote(name)).get("results")
        except Exception as e:
            self.app.internet_result(False)
            self.error = "lookup failed: %s" % e
            print("Weather:", self.error)
            return
        if not found:
            self.error = "place not found: %s" % name
            print("Weather:", self.error)
            return
        place = found[0]
        self._use_place(place["name"], place["latitude"], place["longitude"], place.get("country", ""), auto=False)

    def _fetch(self):
        try:
            data = self._get(_FORECAST % (self.cfg["latitude"], self.cfg["longitude"]))
            current, daily = data["current"], data["daily"]
            self.now = {
                "temperature": current["temperature_2m"],
                "feels_like": current["apparent_temperature"],
                "humidity": current["relative_humidity_2m"],
                "code": current["weather_code"],
                "wind": current["wind_speed_10m"],
                "day": bool(current["is_day"]),
                "high": daily["temperature_2m_max"][0],
                "low": daily["temperature_2m_min"][0],
                "rain_chance": daily["precipitation_probability_max"][0],
            }
            self.fetched = time.ticks_ms()
            self._next = time.ticks_add(self.fetched, _EVERY_MS)
            self.error = None
            self.app.internet_result(True)
        except Exception as e:   # no internet, server busy, bad answer: try again later
            self.error = str(e)
            self.app.internet_result(False)
            self._next = time.ticks_add(time.ticks_ms(), _RETRY_MS)
            print("Weather: fetch failed:", e)

    def age_s(self):
        return None if self.fetched is None else time.ticks_diff(time.ticks_ms(), self.fetched) // 1000
