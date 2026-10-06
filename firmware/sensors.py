# The ENS160 + AHT21 combo board: ENS160 air quality (AQI, TVOC, eCO2) and
# AHT21 temperature/humidity, both on I2C. Register details: docs/sensors.md.
#
# AirSensor runs both from the main loop without blocking: call update() about
# every 20-50 ms. The ENS160 gets the AHT21's temperature and humidity as
# compensation, which its readings need to be accurate.
#
# Written compactly on purpose: on the ESP8266 every line of code costs RAM.
import math
import time

from micropython import const

_ENS = const(0x53)
_AHT = const(0x38)

# ENS160 registers
_PART_ID = const(0x00)
_OPMODE = const(0x10)
_CONFIG = const(0x11)
_COMMAND = const(0x12)
_TEMP_IN = const(0x13)   # 4 bytes: TEMP_IN, RH_IN
_STATUS = const(0x20)
_DATA = const(0x21)      # 5 bytes: AQI, TVOC, ECO2

# ENS160 status bits
_RUNNING = const(0x80)   # STATAS: the selected mode is running
_ERROR = const(0x40)
_NEW_DATA = const(0x02)

# Validity (status bits 3:2). Readings are only meaningful when NORMAL.
NORMAL = const(0)
VALIDITY_NAMES = ("normal", "warm-up", "start-up", "invalid")
_WARMUP_S = (180, 180, 3600, 180)   # by validity; warm-up ~3 min, a new sensor's start-up ~1 h

_AHT_PERIOD_MS = const(2000)   # faster heats the AHT21 itself (datasheet)
_RETRY_MS = const(30000)


def _crc8(data):
    crc = 0xFF
    for byte in data[:6]:
        crc ^= byte
        for _ in range(8):
            crc = (crc << 1 ^ 0x31) & 0xFF if crc & 0x80 else crc << 1 & 0xFF
    return crc


def _magnus(t):
    return 17.62 * t / (243.12 + t)


class AirSensor:
    """Both sensors and their latest readings.

    Attributes (None until the first reading, or while that sensor is missing):
    temperature, humidity (AHT21); aqi, tvoc, eco2, validity, status (ENS160).
    has_air / has_climate say which sensor answers; a missing one is looked
    for again every 30 s. sums collects samples for averaging (see take_sums).
    """

    def __init__(self, i2c, temperature_offset=0.0):
        self.i2c = i2c
        self.offset = temperature_offset
        self.has_air = self.has_climate = False
        self.temperature = self.humidity = None
        self.aqi = self.tvoc = self.eco2 = self.validity = self.status = None
        self.errors = 0
        self.sums = [0.0] * 8   # temperature, humidity, eco2, tvoc: sum and count each
        now = time.ticks_ms()
        self._started = self._next_aht = now
        self._measuring = None   # ticks when an AHT21 measurement was started
        self._retry = now
        self._connect()

    @property
    def valid(self):
        """Air readings (AQI, TVOC, eCO2) are meaningful."""
        return self.has_air and self.validity == NORMAL and self.eco2 is not None

    def warmup_left_s(self):
        """(seconds left, total) of the ENS160 warm-up, estimated from its start."""
        total = _WARMUP_S[self.validity or 0]
        return max(0, total - time.ticks_diff(time.ticks_ms(), self._started) // 1000), total

    def take_sums(self):
        """The sums and counts since the last call, then start over."""
        sums, self.sums = self.sums, [0.0] * 8
        return sums

    def update(self):
        now = time.ticks_ms()
        if not (self.has_air and self.has_climate) and time.ticks_diff(now, self._retry) >= 0:
            self._connect()
        if self.has_climate:
            try:
                self._update_aht(now)
            except OSError as e:
                self._lost("AHT21", e)
                self.has_climate = False
                self._measuring = self.temperature = self.humidity = None
        if self.has_air:
            try:
                self._update_ens()
            except OSError as e:
                self._lost("ENS160", e)
                self.has_air = False
                self.aqi = self.tvoc = self.eco2 = self.validity = self.status = None

    # --- internals --------------------------------------------------------------

    def _lost(self, name, error):
        self.errors += 1
        print(name, "stopped answering:", error)

    def _ens_write(self, reg, value):
        self.i2c.writeto_mem(_ENS, reg, bytes((value,)))

    def _connect(self):
        i2c = self.i2c
        self._retry = time.ticks_add(time.ticks_ms(), _RETRY_MS)
        if not self.has_climate:
            try:
                time.sleep_ms(40)   # AHT21 power-on time
                if not i2c.readfrom(_AHT, 1)[0] & 0x08:   # not calibrated yet
                    i2c.writeto(_AHT, b"\xbe\x08\x00")
                    time.sleep_ms(10)
                self.has_climate = True
                print("AHT21 found")
            except OSError as e:
                print("AHT21 not found:", e)
        if not self.has_air:
            try:
                if i2c.readfrom_mem(_ENS, _PART_ID, 2) != b"\x60\x01":
                    raise OSError("wrong part id")
                for reg, value in ((_OPMODE, 0xF0), (_OPMODE, 0x01), (_CONFIG, 0x00),
                                   (_COMMAND, 0xCC), (_OPMODE, 0x02)):   # reset, idle, no IRQ, clear, run
                    self._ens_write(reg, value)
                    time.sleep_ms(10)
                self._started = time.ticks_ms()
                self.has_air = True
                print("ENS160 found")
            except OSError as e:
                print("ENS160 not found:", e)

    def _add(self, index, value):
        self.sums[index] += value
        self.sums[index + 1] += 1

    def _update_aht(self, now):
        if self._measuring is not None and time.ticks_diff(now, self._measuring) >= 80:
            self._measuring = None
            d = self.i2c.readfrom(_AHT, 7)
            if not d[0] & 0x80 and _crc8(d) == d[6]:   # not busy, CRC ok
                humidity = (d[1] << 12 | d[2] << 4 | d[3] >> 4) * 100 / 1048576
                temperature = ((d[3] & 0x0F) << 16 | d[4] << 8 | d[5]) * 200 / 1048576 - 50
                if self.offset:
                    # Same water vapour, different temperature: correct the RH to match.
                    humidity *= math.exp(_magnus(temperature) - _magnus(temperature + self.offset))
                    temperature += self.offset
                self.temperature = temperature
                self.humidity = humidity = min(100.0, max(0.0, humidity))
                self._add(0, temperature)
                self._add(2, humidity)
                if self.has_air:   # compensation: (T + 273.15) * 64, RH * 512
                    t = int((temperature + 273.15) * 64 + 0.5)
                    h = int(humidity * 512 + 0.5)
                    self.i2c.writeto_mem(_ENS, _TEMP_IN, bytes((t & 0xFF, t >> 8, h & 0xFF, h >> 8)))
        if self._measuring is None and time.ticks_diff(now, self._next_aht) >= 0:
            self.i2c.writeto(_AHT, b"\xac\x33\x00")
            self._measuring = now
            self._next_aht = time.ticks_add(now, _AHT_PERIOD_MS)

    def _update_ens(self):
        status = self.i2c.readfrom_mem(_ENS, _STATUS, 1)[0]
        if status & _ERROR:
            raise OSError("ENS160 error status 0x%02x" % status)
        if not status & _NEW_DATA:
            return
        d = self.i2c.readfrom_mem(_ENS, _DATA, 5)
        self.status = status
        # Not running yet (right after the reset) counts as warm-up: the data is all zeros then.
        self.validity = status >> 2 & 3 if status & _RUNNING else 1
        self.aqi, self.tvoc, self.eco2 = d[0] & 7, d[1] | d[2] << 8, d[3] | d[4] << 8
        if self.validity == NORMAL:
            self._add(4, self.eco2)
            self._add(6, self.tvoc)
