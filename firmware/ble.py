# Bluetooth LE (ESP32 only): the same GATT service and advertising as the
# Thunderboard "BLE Sensor" firmware, so the BLE Sensor phone app finds this
# board in its scan and connects to it, plus BTHome broadcasts for Home
# Assistant. The protocol is described in docs/bluetooth.md.
#
# Advertising alternates every second between two packets (MicroPython has a
# single advertising slot):
#   app packet:    flags | 128-bit service UUID | manufacturer data
#                  (company 0x02FF, board id 0x0C, protocol version)
#   BTHome packet: flags | service data 0xFCD2: packet id, temperature,
#                  humidity, dew point, CO2, TVOC
# The scan response carries the name. While a phone is connected, only the
# BTHome packet goes out (not connectable), so Home Assistant keeps getting data.
import struct
import time

import bluetooth
from micropython import const

import sensors

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

PROTOCOL_VERSION = const(1)
BOARD_ID = const(0x0C)            # "ESP32 Air" (Thunderboards are 0x0A/0x0B)
_COMPANY_ID = const(0x02FF)
_SENSOR_RHT = const(1 << 0)
_SENSOR_AIR = const(1 << 6)
_ENV_VALID_TEMPERATURE = const(1 << 0)
_ENV_VALID_HUMIDITY = const(1 << 1)

COMMAND_FACTORY_RESET = const(0x02)
COMMAND_REBOOT = const(0x03)
COMMAND_IDENTIFY = const(0x04)

NAME_MAX = const(20)
PAGE_MS_MIN = const(1000)
PAGE_MS_MAX = const(60000)

# Display.page_mask bits shared with the Thunderboard; 10-12 are this board's.
PAGE_BITS = {"temperature": 1 << 0, "humidity": 1 << 1, "air": 1 << 10, "eco2": 1 << 11, "tvoc": 1 << 12,
             "dewpoint": 1 << 13, "sensor": 1 << 14, "system": 1 << 15}
_PAGE_ORDER = ("air", "eco2", "tvoc", "temperature", "humidity", "dewpoint", "sensor", "system")   # app.PAGE_NAMES

# Air.state values: the ENS160 validity, or 0xFF without a sensor.
_STATE_NO_SENSOR = const(0xFF)

_ADV_SWITCH_MS = const(1000)
_UPDATE_MS = const(2000)
_SYSTEM_MS = const(5000)
_NONE_I16 = const(0x7FFF)   # "no value" in signed 16-bit fields
_ADV_INTERVAL_US = const(100000)


def _uuid(short):
    return bluetooth.UUID("a7e400%02x-5c2b-4f1a-9d3e-6b8c0f2e1d47" % short)


_SERVICE_UUID = _uuid(0x00)
_ENV = (_uuid(0x01), _FLAG_READ | _FLAG_NOTIFY)
_INFO = (_uuid(0x06), _FLAG_READ)
_COMMAND = (_uuid(0x07), _FLAG_WRITE)
_NAME = (_uuid(0x08), _FLAG_READ | _FLAG_WRITE)
_DISPLAY = (_uuid(0x09), _FLAG_READ | _FLAG_WRITE)
_AIR = (_uuid(0x0A), _FLAG_READ | _FLAG_NOTIFY)
_SYSTEM = (_uuid(0x0B), _FLAG_READ | _FLAG_NOTIFY)
_SERVICE = (_SERVICE_UUID, (_ENV, _INFO, _COMMAND, _NAME, _DISPLAY, _AIR, _SYSTEM))


def _ad(ad_type, payload):
    return bytes((len(payload) + 1, ad_type)) + payload


class Ble:
    def __init__(self, app):
        self.app = app
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        mac = self.ble.config("mac")[1]
        cfg = app.cfg["bluetooth"]
        self.name = cfg["name"] or "Air-Monitor-%02X%02X" % (mac[4], mac[5])
        self.bthome = cfg["bthome"]
        self.ble.config(gap_name=self.name)
        ((self.h_env, self.h_info, self.h_command, self.h_name, self.h_display, self.h_air, self.h_system),) = \
            self.ble.gatts_register_services((_SERVICE,))
        self.ble.gatts_set_buffer(self.h_name, NAME_MAX)
        self.ble.irq(self._irq)
        self.connection = None
        self.pending = []          # writes from the IRQ, handled in poll()
        self.packet_id = 0
        self.show_bthome = False
        self.identify_until = None
        self._next_adv = self._next_update = self._next_system = time.ticks_ms()

        self.ble.gatts_write(self.h_info, struct.pack("<BBBB", PROTOCOL_VERSION, BOARD_ID,
                                                      _SENSOR_RHT | _SENSOR_AIR, 0))
        self.ble.gatts_write(self.h_name, self.name.encode())
        self.write_display()
        self._update_values(notify=False)
        print("Bluetooth: advertising as", self.name)

    # --- main loop -------------------------------------------------------------

    def poll(self):
        now = time.ticks_ms()
        while self.pending:
            self._handle_write(*self.pending.pop(0))
        if time.ticks_diff(now, self._next_update) >= 0:
            self._next_update = time.ticks_add(now, _UPDATE_MS)
            self._update_values(notify=self.connection is not None)
        if time.ticks_diff(now, self._next_system) >= 0:
            self._next_system = time.ticks_add(now, _SYSTEM_MS)
            self._update_system(notify=self.connection is not None)
        if time.ticks_diff(now, self._next_adv) >= 0:
            self._next_adv = time.ticks_add(now, _ADV_SWITCH_MS)
            self._advertise()
        if self.identify_until is not None:
            display = self.app.display
            if time.ticks_diff(now, self.identify_until) >= 0:
                self.identify_until = None
                if display:
                    display.oled.invert(False)
            elif display:
                display.oled.invert(now // 250 % 2)

    # --- values ---------------------------------------------------------------

    def _update_values(self, notify):
        air = self.app.air
        uptime = time.ticks_ms() & 0xFFFFFFFF
        valid = 0
        temperature = humidity = 0
        if air.temperature is not None:
            valid |= _ENV_VALID_TEMPERATURE
            temperature = int(air.temperature * 100)
        if air.humidity is not None:
            valid |= _ENV_VALID_HUMIDITY
            humidity = int(air.humidity * 100)
        env = struct.pack("<IHhHIHiBhHh", uptime, valid, temperature, humidity, 0, 0, 0, 0, 0, 0, 0)
        state = _STATE_NO_SENSOR if air.validity is None else air.validity
        ok = air.valid
        fw = air.firmware or (0, 0, 0)
        # Air: the first 10 bytes are the original layout; details follow.
        air_value = struct.pack(
            "<IBBHHBBBBHHhH", uptime, state, air.aqi if ok else 0, air.eco2 if ok else 0, air.tvoc if ok else 0,
            air.status or 0, fw[0], fw[1], fw[2], air.r1_raw or 0, air.r4_raw or 0,
            _NONE_I16 if air.comp_t is None else int(air.comp_t * 100),
            0 if air.comp_rh is None else int(air.comp_rh * 100))
        self.ble.gatts_write(self.h_env, env)
        self.ble.gatts_write(self.h_air, air_value)
        if notify:
            self._notify(((self.h_env, env), (self.h_air, air_value)))

    def _update_system(self, notify):
        app, air = self.app, self.app.air
        info = app.system_info()
        ip = bytes(int(part) for part in info["ip"].split(".")) if info["ip"] else b"\0\0\0\0"
        chip = info["chip_temperature"]
        flags = (1 if info["wifi"] else 0) | (2 if info["mqtt"] else 0) | (4 if info["bluetooth"] else 0)
        mp = info["micropython"]
        value = struct.pack(
            "<IIhbB4sHBBBBHHIH", info["uptime_s"], info["free_ram"],
            _NONE_I16 if chip is None else int(chip * 100), info["wifi_rssi"] or 0, flags, ip,
            info["cpu_mhz"], info["reset_cause"], mp[0], mp[1], mp[2],
            min(air.errors, 0xFFFF), min(air.integrity_errors, 0xFFFF), air.humid_s, 0)
        self.ble.gatts_write(self.h_system, value)
        if notify:
            self._notify(((self.h_system, value),))

    def _notify(self, values):
        for handle, value in values:
            try:
                self.ble.gatts_notify(self.connection, handle, value)
            except OSError:   # not subscribed yet, or just disconnected
                pass

    def write_display(self):
        cfg = self.app.cfg["display"]
        mask = 0
        for page in cfg["pages"]:
            mask |= PAGE_BITS.get(page, 0)
        self.ble.gatts_write(self.h_display, struct.pack(
            "<BHH", 1 if self.app.display else 0, mask, int(cfg["page_s"] * 1000)))

    # --- advertising ------------------------------------------------------------

    def _app_packet(self):
        return (_ad(0x01, b"\x06") + _ad(0x07, bytes(_SERVICE_UUID))
                + _ad(0xFF, struct.pack("<HBB", _COMPANY_ID, BOARD_ID, PROTOCOL_VERSION)))

    def _bthome_packet(self):
        air = self.app.air
        self.packet_id = (self.packet_id + 1) & 0xFF
        data = bytearray(b"\xd2\xfc\x40")   # UUID 0xFCD2, BTHome v2, not encrypted
        data += struct.pack("<BB", 0x00, self.packet_id)
        if air.temperature is not None:
            data += struct.pack("<Bh", 0x02, int(air.temperature * 100))
        if air.humidity is not None:
            data += struct.pack("<BH", 0x03, int(air.humidity * 100))
        dew = sensors.dew_point(air.temperature, air.humidity)
        if dew is not None:
            data += struct.pack("<Bh", 0x08, int(dew * 100))
        if air.valid:
            data += struct.pack("<BH", 0x12, air.eco2)
            # BTHome wants TVOC in µg/m³; the ENS160's is ethanol-calibrated (see sensors.tvoc_ugm3).
            data += struct.pack("<BH", 0x13, min(0xFFFF, int(sensors.tvoc_ugm3(air.tvoc, air.temperature))))
        return _ad(0x01, b"\x06") + _ad(0x16, bytes(data))

    def _advertise(self):
        connected = self.connection is not None
        if not self.bthome and connected:
            return
        self.show_bthome = self.bthome and (connected or not self.show_bthome)
        packet = self._bthome_packet() if self.show_bthome else self._app_packet()
        try:
            self.ble.gap_advertise(_ADV_INTERVAL_US, adv_data=packet,
                                   resp_data=_ad(0x09, self.name.encode()), connectable=not connected)
        except OSError as e:
            print("Bluetooth: advertising failed:", e)

    # --- events -----------------------------------------------------------------

    def _irq(self, event, data):
        # Runs in a callback: keep it short, the real work is done in poll().
        if event == _IRQ_CENTRAL_CONNECT:
            self.connection = data[0]
            self._next_adv = time.ticks_ms()
            print("Bluetooth: phone connected")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.connection = None
            self._next_adv = time.ticks_ms()
            print("Bluetooth: phone disconnected")
        elif event == _IRQ_GATTS_WRITE:
            handle = data[1]
            self.pending.append((handle, bytes(self.ble.gatts_read(handle))))

    def _handle_write(self, handle, value):
        app = self.app
        if handle == self.h_command and value:
            command = value[0]
            print("Bluetooth: command", command)
            if command == COMMAND_REBOOT:
                app.reboot_at = time.ticks_add(time.ticks_ms(), 500)
            elif command == COMMAND_IDENTIFY:
                self.identify_until = time.ticks_add(time.ticks_ms(), 3000)
            elif command == COMMAND_FACTORY_RESET:
                app.factory_reset()
        elif handle == self.h_name:
            try:
                name = value.decode().strip()
            except UnicodeError:
                name = ""
            if 0 < len(value) <= NAME_MAX and name:
                self.name = name
                app.cfg["bluetooth"]["name"] = name
                app.save_settings()
                self.ble.config(gap_name=name)
                print("Bluetooth: renamed to", name)
            self.ble.gatts_write(self.h_name, self.name.encode())
        elif handle == self.h_display:
            # A rejected write can't be refused over the air from MicroPython:
            # the old value is written back, and the app sees it on its next read.
            if len(value) == 5:
                _, mask, page_ms = struct.unpack("<BHH", value)
                cfg = app.cfg["display"]
                # The mask has no order: keep the current order, append new pages.
                chosen = [p for p in cfg["pages"] if PAGE_BITS[p] & mask] + \
                    [p for p in _PAGE_ORDER if PAGE_BITS[p] & mask and p not in cfg["pages"]]
                if chosen and PAGE_MS_MIN <= page_ms <= PAGE_MS_MAX:
                    cfg["pages"], cfg["page_s"] = chosen, page_ms / 1000
                    if app.display:
                        app.display.set_pages(chosen)
                    app.save_settings()
                    print("Bluetooth: display", chosen, "every", page_ms, "ms")
            self.write_display()
