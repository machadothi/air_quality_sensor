"""MicroPython stand-ins, so the real firmware runs under CPython in tests.

install() puts fake modules (machine, network, bluetooth, umqtt.simple, esp32,
ntptime, requests, micropython, framebuf, ssd1306) into sys.modules, adds the
MicroPython-only functions to time/gc/sys, and returns a Board: the state the
tests drive and look at (clock, Wi-Fi networks in range, Bluetooth calls).
Nothing here talks to real hardware; tests/hardware/ is for the real board.
"""

import gc
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Reset(Exception):
    """machine.reset() was called."""


class Board:
    def __init__(self):
        self.ms = 0                     # time.ticks_ms()
        self.rtc = 0                    # time.time(): seconds since 2000 (0 = never set)
        self.networks = {}              # SSID -> password, in range
        self.ble = None                 # the FakeBLE the firmware created
        self.i2c_devices = {}           # address -> handler (none: no sensors, no display)


board = Board()


# --- time, gc, sys ---------------------------------------------------------------

_UNIX_2000 = 946684800


def _install_runtime():
    import calendar
    real_gmtime = getattr(time, "_real_gmtime", time.gmtime)
    time._real_gmtime = real_gmtime
    # MicroPython: integer seconds since 2000, gmtime/localtime/mktime on that epoch.
    time.time = lambda: board.rtc + board.ms // 1000
    time.gmtime = time.localtime = lambda t=None: tuple(real_gmtime((time.time() if t is None else t) + _UNIX_2000))[:8]
    time.mktime = lambda t: calendar.timegm(tuple(t[:6]) + (0, 0, 0)) - _UNIX_2000
    time.ticks_ms = lambda: board.ms
    time.ticks_add = lambda a, b: a + b
    time.ticks_diff = lambda a, b: a - b
    time.sleep_ms = lambda ms: setattr(board, "ms", board.ms + ms)
    gc.mem_free = lambda: 100000
    gc.mem_alloc = lambda: 20000
    sys.print_exception = lambda e, *a: print("Traceback:", type(e).__name__, e)


# --- machine ---------------------------------------------------------------------------

def _machine():
    m = types.ModuleType("machine")

    class Pin:
        OUT, IN = 1, 0

        def __init__(self, *a, **k):
            self.state = k.get("value", 0)

        def __call__(self, value=None):
            if value is not None:
                self.state = value
            return self.state

    class I2C:
        def __init__(self, *a, **k):
            pass

        def scan(self):
            return sorted(board.i2c_devices)

        def _dev(self, addr):
            if addr not in board.i2c_devices:
                raise OSError(19)   # ENODEV, like a missing chip
            return board.i2c_devices[addr]

        def writeto(self, addr, buf, stop=True):
            return self._dev(addr).write(bytes(buf))

        def readfrom(self, addr, n, stop=True):
            return self._dev(addr).read(n)

        def writeto_mem(self, addr, reg, buf, **k):
            self._dev(addr).write(bytes([reg]) + bytes(buf))

        def readfrom_mem(self, addr, reg, n, **k):
            self._dev(addr).write(bytes([reg]))
            return self._dev(addr).read(n)

        def readfrom_mem_into(self, addr, reg, buf, **k):
            buf[:] = self.readfrom_mem(addr, reg, len(buf))

        def readfrom_into(self, addr, buf, stop=True):
            buf[:] = self.readfrom(addr, len(buf))

        def writevto(self, addr, bufs, stop=True):
            self.writeto(addr, b"".join(bytes(b) for b in bufs))

    class Timer:
        PERIODIC = ONE_SHOT = 0

        def __init__(self, *a):
            pass

        def init(self, **k):
            pass

        def deinit(self):
            pass

    class RTC:
        _memory = b""

        def memory(self, data=None):
            if data is not None:
                RTC._memory = bytes(data)
            return RTC._memory

        def datetime(self, t=None):
            if t is not None:   # (year, month, day, weekday, hour, minute, second, subseconds)
                board.rtc = time.mktime((t[0], t[1], t[2], t[4], t[5], t[6], 0, 0)) - board.ms // 1000
            return t

    def reset():
        raise Reset()

    m.Pin, m.I2C, m.SoftI2C, m.Timer, m.RTC = Pin, I2C, I2C, Timer, RTC
    m.reset = m.soft_reset = reset
    m.freq = lambda *a: 160000000
    m.reset_cause = lambda: 1
    m.unique_id = lambda: b"\x01\x02\x03\x04\x05\x06"
    m.PWRON_RESET, m.HARD_RESET, m.WDT_RESET, m.DEEPSLEEP_RESET, m.SOFT_RESET = 1, 2, 3, 4, 5
    return m


# --- network (ESP32 driver behaviour) ---------------------------------------------------

def _network():
    n = types.ModuleType("network")
    n.STA_IF, n.AP_IF = 0, 1
    n.STAT_IDLE, n.STAT_CONNECTING, n.STAT_GOT_IP = 1000, 1001, 1010
    n.STAT_NO_AP_FOUND, n.STAT_WRONG_PASSWORD = 201, 202

    class WLAN:
        """Like the ESP32 driver: it keeps retrying by itself after connect(),
        refuses a second connect() meanwhile, and can't scan while connecting."""

        def __init__(self, interface):
            self.requested = self.ok = False
            self.ssid = None

        def active(self, *a):
            return True

        def isconnected(self):
            return self.ok

        def status(self, *a):
            if a:
                return -55
            if not self.requested:
                return n.STAT_IDLE
            if self.ok:
                return n.STAT_GOT_IP
            if self.ssid in board.networks:
                return n.STAT_WRONG_PASSWORD
            return n.STAT_NO_AP_FOUND

        def connect(self, ssid, password):
            if not ssid:
                raise OSError("Wifi Invalid Argument")
            if self.requested:
                raise OSError("Wifi Internal Error")
            self.requested, self.ssid = True, ssid
            self.ok = board.networks.get(ssid) == password

        def disconnect(self):
            self.requested = self.ok = False

        def scan(self):
            if self.requested and not self.ok:
                raise OSError("Wifi Internal State Error")
            return [(name.encode(), b"\0" * 6, 1, -50 - i, 3, 0) for i, name in enumerate(board.networks)]

        def ifconfig(self):
            return ("192.0.2.10", "255.255.255.0", "192.0.2.1", "192.0.2.1")

    stations = {}
    n.WLAN = lambda interface: stations.setdefault(interface, WLAN(interface))
    return n


# --- bluetooth -------------------------------------------------------------------------

class FakeBLE:
    def __init__(self):
        self.settings = {}
        self.services = None
        self.values = {}
        self.irq_handler = None
        self.passkeys = []        # (conn, action, passkey) given to gap_passkey
        self.adverts = 0
        board.ble = self

    def active(self, *a):
        return True

    def config(self, *args, **kwargs):
        if args:
            return {"mac": (0, b"\xaa\xbb\xcc\xdd\x50\x7e")}.get(args[0])
        self.settings.update(kwargs)

    def irq(self, handler):
        self.irq_handler = handler

    def gatts_register_services(self, services):
        self.services = services
        handles, h = [], 1
        for _, chars in services:
            handles.append(tuple(range(h, h + len(chars))))
            h += len(chars)
        return handles

    def gatts_set_buffer(self, handle, size, *a):
        pass

    def gatts_write(self, handle, value, *a):
        self.values[handle] = bytes(value)

    def gatts_read(self, handle):
        return self.values.get(handle, b"")

    def gatts_notify(self, *a):
        pass

    def gap_advertise(self, *a, **k):
        self.adverts += 1

    def gap_passkey(self, conn, action, passkey):
        self.passkeys.append((conn, action, passkey))

    # helpers for tests: what a phone would do
    def phone_writes(self, handle, value):
        self.values[handle] = bytes(value)
        return self.irq_handler(3, (0, handle))

    def flags(self, uuid_short):
        for _, chars in self.services:
            for uuid, flags in chars:
                if str(uuid).startswith("a7e400%02x" % uuid_short):
                    return flags
        raise KeyError(uuid_short)


def _bluetooth():
    b = types.ModuleType("bluetooth")
    b.BLE = FakeBLE

    class UUID:
        def __init__(self, value):
            self.value = value

        def __str__(self):
            return str(self.value)

        def __bytes__(self):   # MicroPython: 16 bytes, little-endian
            import uuid
            return uuid.UUID(self.value).bytes[::-1]

    b.UUID = UUID
    return b


# --- MQTT ------------------------------------------------------------------------------

def _umqtt():
    pkg, simple = types.ModuleType("umqtt"), types.ModuleType("umqtt.simple")

    class MQTTException(Exception):
        pass

    class MQTTClient:
        broker_up = False
        inbox = []          # messages check_msg() delivers, or exceptions it raises

        def __init__(self, *a, **k):
            self.sock = types.SimpleNamespace(close=lambda: None)

        def set_callback(self, f):
            self.callback = f

        def set_last_will(self, *a, **k):
            pass

        def connect(self):
            if not MQTTClient.broker_up:
                raise OSError("ECONNREFUSED")

        def subscribe(self, topic):
            pass

        def publish(self, *a, **k):
            pass

        def ping(self):
            pass

        def disconnect(self):
            pass

        def check_msg(self):
            while MQTTClient.inbox:
                item = MQTTClient.inbox.pop(0)
                if isinstance(item, Exception):
                    raise item
                self.callback(b"esp/test/request", item)

    simple.MQTTClient, simple.MQTTException = MQTTClient, MQTTException
    pkg.simple = simple
    return pkg, simple


def install():
    """Fake modules in, firmware on the path. Returns the Board."""
    _install_runtime()
    micropython = types.ModuleType("micropython")
    micropython.const = lambda x: x
    micropython.mem_info = lambda *a: None
    esp32 = types.ModuleType("esp32")
    esp32.mcu_temperature = lambda: 45
    esp32.raw_temperature = lambda: 113   # °F, like the ESP32's die sensor
    sys.implementation._mpy = 6           # MicroPython 1.24's .mpy format
    ntptime = types.ModuleType("ntptime")

    def settime():
        raise OSError("no internet in tests")
    ntptime.settime = settime
    requests = types.ModuleType("requests")

    def get(*a, **k):
        raise OSError("no internet in tests")
    requests.get = get
    umqtt, simple = _umqtt()
    sys.modules.update({
        "micropython": micropython, "machine": _machine(), "network": _network(), "bluetooth": _bluetooth(),
        "umqtt": umqtt, "umqtt.simple": simple, "esp32": esp32, "ntptime": ntptime, "requests": requests,
    })
    for path in (ROOT / "tools" / "sim", ROOT / "firmware"):   # framebuf, ssd1306 stand-ins; the firmware
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return board
