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

import machine
from micropython import const

_ENS = const(0x53)
_AHT = const(0x38)

# ENS160 registers (datasheet SC-001224-DS-9)
_PART_ID = const(0x00)
_OPMODE = const(0x10)
_CONFIG = const(0x11)
_COMMAND = const(0x12)
_TEMP_IN = const(0x13)   # 4 bytes: TEMP_IN, RH_IN
_STATUS = const(0x20)
_DATA = const(0x21)      # 5 bytes: AQI, TVOC, ECO2
_DATA_T = const(0x30)    # 4 bytes: DATA_T, DATA_RH: the compensation in use
_MISR = const(0x38)      # running checksum of the bytes read (see _ens_read)
_GPR_READ = const(0x48)  # 8 bytes: raw resistances, or the firmware version

_MODE_IDLE = const(0x01)
_MODE_STANDARD = const(0x02)
_CMD_GET_APPVER = const(0x0E)
_CMD_CLEAR_GPR = const(0xCC)

# ENS160 status bits
_RUNNING = const(0x80)   # STATAS: the selected mode is running
_ERROR = const(0x40)
_NEW_DATA = const(0x02)
_NEW_GPR = const(0x01)

# Validity (status bits 3:2). Readings are only meaningful when NORMAL.
NORMAL = const(0)
VALIDITY_NAMES = ("normal", "warm-up", "start-up", "invalid")
_WARMUP_S = (180, 180, 3600, 180)   # by validity; warm-up ~3 min, a new sensor's start-up ~1 h

_AHT_PERIOD_MS = const(2000)   # datasheet: at least 1 s apart, or it heats itself
_RETRY_MS = const(30000)
_COMP_READ_MS = const(10000)
_HUMID_RH = const(80)          # AHT21 datasheet: long stays above 80 %RH cause drift

# Remembers the ENS160 firmware version across ESP restarts (the sensor keeps
# running, and the version can only be read after a reset to idle).
_RTC_TAG = b"ENS160:"


def _crc8(data):
    crc = 0xFF
    for byte in data[:6]:
        crc ^= byte
        for _ in range(8):
            crc = (crc << 1 ^ 0x31) & 0xFF if crc & 0x80 else crc << 1 & 0xFF
    return crc


def _magnus(t):
    return 17.62 * t / (243.12 + t)


def dew_point(temperature, humidity):
    """Dew point in °C (Magnus formula), or None."""
    if temperature is None or not humidity:
        return None
    gamma = math.log(humidity / 100) + _magnus(temperature)
    return 243.12 * gamma / (17.62 - gamma)


def absolute_humidity(temperature, humidity):
    """Water vapour in g/m³, or None."""
    if temperature is None or humidity is None:
        return None
    return 216.7 * humidity / 100 * 6.112 * math.exp(_magnus(temperature)) / (273.15 + temperature)


def tvoc_ugm3(tvoc_ppb, temperature):
    """TVOC in µg/m³. The ENS160's TVOC is ethanol-calibrated (DATA_ETOH mirrors
    it), so convert with ethanol's molar mass at the current temperature."""
    if tvoc_ppb is None:
        return None
    molar_volume = 22.414 * (273.15 + (temperature if temperature is not None else 25)) / 273.15
    return tvoc_ppb * 46.07 / molar_volume


class AirSensor:
    """Both sensors and their latest readings.

    Attributes (None until the first reading, or while that sensor is missing):
      temperature, humidity (AHT21); aqi, tvoc, eco2, validity, status (ENS160);
      r1_raw, r4_raw: ENS160 raw resistances of sensors 1 and 4 (ohms = 2^(raw/2048));
      comp_t, comp_rh: the compensation the ENS160 says it uses;
      firmware: ENS160 firmware (major, minor, release).
    Counters: errors (sensor lost), integrity_errors (ENS160 checksum mismatch),
    humid_s (seconds above 80 %RH since start).
    has_air / has_climate say which sensor answers; a missing one is looked for
    again every 30 s. sums collects samples for averaging (see take_sums).
    """

    def __init__(self, i2c, temperature_offset=0.0):
        self.i2c = i2c
        self.offset = temperature_offset
        self.has_air = self.has_climate = False
        self.temperature = self.humidity = None
        self.aqi = self.tvoc = self.eco2 = self.validity = self.status = None
        self.r1_raw = self.r4_raw = self.comp_t = self.comp_rh = self.firmware = None
        self.errors = self.integrity_errors = self.humid_s = 0
        self.sums = [0.0] * 8   # temperature, humidity, eco2, tvoc: sum and count each
        now = time.ticks_ms()
        self._started = self._next_aht = self._next_comp = now
        self._measuring = None   # ticks when an AHT21 measurement was started
        self._retry = now
        self._misr = 0           # our copy of the ENS160's checksum
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
                self._update_ens(now)
            except OSError as e:
                self._lost("ENS160", e)
                self.has_air = False
                self.aqi = self.tvoc = self.eco2 = self.validity = self.status = None
                self.r1_raw = self.r4_raw = self.comp_t = self.comp_rh = None

    # --- internals --------------------------------------------------------------

    def _lost(self, name, error):
        self.errors += 1
        print(name, "stopped answering:", error)

    def _ens_write(self, reg, value):
        self.i2c.writeto_mem(_ENS, reg, bytes((value,)))

    def _ens_read(self, reg, n):
        """Read, and keep our copy of DATA_MISR in step. The datasheet says the
        checksum covers registers 0x20-0x37; measured on a real ENS160 (firmware
        5.4.6), every read except DATA_MISR itself updates it, so all count."""
        data = self.i2c.readfrom_mem(_ENS, reg, n)
        misr = self._misr
        for byte in data:
            x = (misr << 1 ^ byte) & 0xFF
            misr = x ^ 0x1D if misr & 0x80 else x
        self._misr = misr
        return data

    def _check_integrity(self):
        """Compare our checksum with the sensor's; a mismatch means a corrupted read."""
        misr = self.i2c.readfrom_mem(_ENS, _MISR, 1)[0]
        if misr != self._misr:
            self.integrity_errors += 1
            self._misr = misr
            return False
        return True

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
                self._connect_ens()
                self.has_air = True
            except OSError as e:
                print("ENS160 not found:", e)

    def _connect_ens(self):
        if self.i2c.readfrom_mem(_ENS, _PART_ID, 2) != b"\x60\x01":
            raise OSError("wrong part id")
        rtc = machine.RTC()
        running = (self.i2c.readfrom_mem(_ENS, _OPMODE, 1)[0] == _MODE_STANDARD
                   and self.i2c.readfrom_mem(_ENS, _STATUS, 1)[0] & _RUNNING)
        saved = rtc.memory()
        if running and saved.startswith(_RTC_TAG):
            # The ESP restarted but the sensor kept measuring: leave it alone, so
            # it doesn't go through the 3-minute warm-up again (datasheet 10.2).
            self.firmware = tuple(saved[len(_RTC_TAG):len(_RTC_TAG) + 3])
            print("ENS160 found, still running, firmware %d.%d.%d" % self.firmware)
        else:
            for reg, value in ((_OPMODE, 0xF0), (_OPMODE, _MODE_IDLE), (_CONFIG, 0x00),
                               (_COMMAND, _CMD_CLEAR_GPR)):   # reset, idle, no IRQ pin, clear
                self._ens_write(reg, value)
                time.sleep_ms(10)
            self._ens_write(_COMMAND, _CMD_GET_APPVER)   # only answered in idle mode
            time.sleep_ms(10)
            self.firmware = tuple(self.i2c.readfrom_mem(_ENS, _GPR_READ + 4, 3))
            rtc.memory(_RTC_TAG + bytes(self.firmware))
            self._ens_write(_OPMODE, _MODE_STANDARD)
            time.sleep_ms(10)
            self._started = time.ticks_ms()
            print("ENS160 found, firmware %d.%d.%d" % self.firmware)
        self._misr = self.i2c.readfrom_mem(_ENS, _MISR, 1)[0]

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
                if humidity > _HUMID_RH:
                    self.humid_s += _AHT_PERIOD_MS // 1000
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

    def _update_ens(self, now):
        status = self._ens_read(_STATUS, 1)[0]
        if status & _ERROR:
            raise OSError("ENS160 error status 0x%02x" % status)
        if status & _NEW_GPR:   # raw resistances of sensors 1 and 4 (datasheet section 7)
            g = self._ens_read(_GPR_READ, 8)
            self.r1_raw, self.r4_raw = g[0] | g[1] << 8, g[6] | g[7] << 8
        if time.ticks_diff(now, self._next_comp) >= 0:   # the compensation it really uses
            self._next_comp = time.ticks_add(now, _COMP_READ_MS)
            c = self._ens_read(_DATA_T, 4)
            self.comp_t = (c[0] | c[1] << 8) / 64 - 273.15
            self.comp_rh = (c[2] | c[3] << 8) / 512
        if not status & _NEW_DATA:
            return
        d = self._ens_read(_DATA, 5)
        if not self._check_integrity():
            return   # corrupted on the bus: skip this reading
        self.status = status
        # Not running yet (right after the reset) counts as warm-up: the data is all zeros then.
        self.validity = status >> 2 & 3 if status & _RUNNING else 1
        self.aqi, self.tvoc, self.eco2 = d[0] & 7, d[1] | d[2] << 8, d[3] | d[4] << 8
        if self.validity == NORMAL:
            self._add(4, self.eco2)
            self._add(6, self.tvoc)
