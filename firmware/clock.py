# Wall-clock time (ESP32): set from the internet (NTP) when Wi-Fi is up, and
# from the phone (the app sends its time and time zone over Bluetooth) when it
# connects. MicroPython has no time-zone database, so the zone is a standard
# UTC offset plus a summer-time rule (EU, US or none), which the app derives
# from the phone's zone.
#
# MicroPython on the ESP32 counts seconds from 2000-01-01 (UTC here).
import time

import machine
from micropython import const

UNIX_2000 = const(946684800)   # 2000-01-01 in Unix time
NONE = const(0)
EU = const(1)
US = const(2)
SOURCES = ("unknown", "internet", "phone")
_NTP_EVERY_MS = const(6 * 3600 * 1000)
_VALID_AFTER = const(800000000)   # seconds since 2000: anything before 2025 means "never set"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _last_sunday(year, month):
    """Day of the month of the last Sunday."""
    days = (31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
    weekday = time.localtime(time.mktime((year, month, days, 0, 0, 0, 0, 0)))[6]   # 0 = Monday
    return days - (weekday + 1) % 7


def _nth_sunday(year, month, n):
    weekday = time.localtime(time.mktime((year, month, 1, 0, 0, 0, 0, 0)))[6]
    return 1 + (6 - weekday) % 7 + 7 * (n - 1)


class Clock:
    def __init__(self, cfg):
        self.cfg = cfg                  # app.cfg["time"]: offset_min, dst
        self.source = 0   # unknown until set (the RTC survives a soft reset, but we can't tell by whom)
        self._next_ntp = time.ticks_ms()

    def known(self):
        return time.time() > _VALID_AFTER

    def utc(self):
        """Seconds since 2000, UTC."""
        return time.time()

    def offset_min(self):
        """Current offset from UTC in minutes, summer time included."""
        return self.cfg["offset_min"] + (60 if self._summer() else 0)

    def _summer(self):
        rule = self.cfg["dst"]
        if rule == NONE:
            return False
        now = time.time()
        year = time.gmtime(now)[0]
        if rule == EU:   # last Sunday of March to last Sunday of October, at 01:00 UTC
            start = time.mktime((year, 3, _last_sunday(year, 3), 1, 0, 0, 0, 0))
            end = time.mktime((year, 10, _last_sunday(year, 10), 1, 0, 0, 0, 0))
        else:            # US: second Sunday of March to first Sunday of November, 02:00 local
            std = self.cfg["offset_min"] * 60
            start = time.mktime((year, 3, _nth_sunday(year, 3, 2), 2, 0, 0, 0, 0)) - std
            end = time.mktime((year, 11, _nth_sunday(year, 11, 1), 2, 0, 0, 0, 0)) - std - 3600
        return start <= now < end

    def local(self):
        """(year, month, day, hour, minute, second, weekday 0=Mon, yearday) or None if unknown."""
        if not self.known():
            return None
        return time.gmtime(time.time() + self.offset_min() * 60)

    def set_utc(self, unix_utc, source):
        t = time.gmtime(unix_utc - UNIX_2000)
        machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
        self.source = source
        print("Clock set from the %s: %04d-%02d-%02d %02d:%02d UTC" % ((SOURCES[source],) + t[:5]))

    def poll(self, wifi_ok):
        """Sync from the internet now and then while Wi-Fi is up."""
        if not wifi_ok or time.ticks_diff(time.ticks_ms(), self._next_ntp) < 0:
            return
        self._next_ntp = time.ticks_add(time.ticks_ms(), _NTP_EVERY_MS)
        try:
            import ntptime
            ntptime.settime()   # blocks up to ~1 s
            self.source = 1
            print("Clock set from the internet")
        except Exception as e:   # no answer: try again in 6 h (or the phone sets it)
            print("Clock: NTP failed:", e)
            self._next_ntp = time.ticks_add(time.ticks_ms(), 600000)
