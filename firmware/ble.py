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
             "dewpoint": 1 << 13, "sensor": 1 << 14, "system": 1 << 15,
             "clock": 1 << 16, "weather": 1 << 17}   # bits 16+ go in the Display value's 7th byte
_PAGE_ORDER = ("air", "eco2", "tvoc", "temperature", "humidity", "dewpoint", "sensor", "system", "clock", "weather")

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
_CALIBRATION = (_uuid(0x0C), _FLAG_READ | _FLAG_WRITE | _FLAG_NOTIFY)
_TIME = (_uuid(0x0D), _FLAG_READ | _FLAG_WRITE)
_WIFI = (_uuid(0x0E), _FLAG_READ | _FLAG_WRITE | _FLAG_NOTIFY)
_WEATHER = (_uuid(0x0F), _FLAG_READ | _FLAG_WRITE)
_UPDATE = (_uuid(0x10), _FLAG_READ | _FLAG_WRITE | _FLAG_NOTIFY)
_SERVICE = (_SERVICE_UUID, (_ENV, _INFO, _COMMAND, _NAME, _DISPLAY, _AIR, _SYSTEM, _CALIBRATION, _TIME, _WIFI,
                            _WEATHER, _UPDATE))

_UNIX_2000 = const(946684800)


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
        ((self.h_env, self.h_info, self.h_command, self.h_name, self.h_display, self.h_air, self.h_system,
          self.h_calibration, self.h_time, self.h_wifi, self.h_weather, self.h_update),) = \
            self.ble.gatts_register_services((_SERVICE,))
        self.ble.gatts_set_buffer(self.h_name, NAME_MAX)
        self.ble.gatts_set_buffer(self.h_display, 6)
        self.ble.gatts_set_buffer(self.h_calibration, 20)
        self.ble.gatts_set_buffer(self.h_time, 12)
        self.ble.gatts_set_buffer(self.h_wifi, 512)
        self.ble.gatts_set_buffer(self.h_weather, 128)
        self.ble.gatts_set_buffer(self.h_update, 320)
        self._update_value = b""
        self.scan_results = []
        self.scanning = False
        self._wifi_value = b""
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
        self.write_calibration()
        self.write_time()
        self.write_wifi(notify=False)
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
            self.write_wifi(notify=self.connection is not None)
            self.write_update(notify=self.connection is not None)
        if time.ticks_diff(now, self._next_system) >= 0:
            self._next_system = time.ticks_add(now, _SYSTEM_MS)
            self._update_system(notify=self.connection is not None)
            self.write_calibration(notify=self.connection is not None)
            self.write_time()
            self.write_weather()
        if self.scanning:   # requested from the app: blocks ~3 s
            self.scan_results = self.app.net.scan()
            self.scanning = False
            self.write_wifi(notify=self.connection is not None)
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
        # 7 bytes: the Thunderboard's 5, flags (bit 0: rotated 180°), page bits 16-23.
        self.ble.gatts_write(self.h_display, struct.pack(
            "<BHHBB", 1 if self.app.display else 0, mask & 0xFFFF, int(cfg["page_s"] * 1000),
            1 if cfg["rotate"] else 0, mask >> 16))

    def write_time(self):
        """Time: u32 Unix time UTC (0 = unknown), i16 standard offset (min),
        u8 summer-time rule, u8 source, i16 current offset (min), u16 reserved."""
        clock = self.app.clock
        known = clock is not None and clock.known()
        self.ble.gatts_write(self.h_time, struct.pack(
            "<IhBBhH", clock.utc() + _UNIX_2000 if known else 0, self.app.cfg["time"]["offset_min"],
            self.app.cfg["time"]["dst"], clock.source if clock else 0, clock.offset_min() if known else 0, 0))

    def write_update(self, notify):
        """Update: u8 state, u8 progress %, then length-prefixed strings: current
        version, available version, release notes, last error. Notified on change."""
        u = self.app.updater
        if u is None:
            return
        st = u.status()   # a check or install restarts the board: "checking" / "downloading" first

        def text(value, limit):
            data = (value or "").encode()[:limit]
            return bytes((len(data),)) + data

        value = (bytes((u.state, u.progress)) + text(st["version"], 16) + text(st["available"], 16)
                 + text(st["notes"], 200) + text(st["error"], 60) + bytes((1 if st["auto"] else 0,)))
        if value != self._update_value:
            self._update_value = value
            self.ble.gatts_write(self.h_update, value)
            if notify and self.connection is not None:
                self._notify(((self.h_update, value),))

    def write_weather(self):
        """Weather: flags (bit 0 on, 1 fresh data, 2 online), current values,
        today's high/low, data age, place, last error. See docs/bluetooth.md."""
        w = self.app.weather
        if w is None:
            return
        now = w.now if w.fresh() else None
        flags = (1 if w.cfg["enabled"] else 0) | (2 if now else 0) | (4 if self.app.online() else 0)

        def x10(value):
            return _NONE_I16 if value is None else int(round(value * 10))

        n = now or {}
        age = w.age_s()
        place = w.cfg["place"].encode()[:40]
        error = (w.error or "").encode()[:60]
        value = struct.pack("<BhhBBBhhhBH", flags, x10(n.get("temperature")), x10(n.get("feels_like")),
                            int(n.get("humidity") or 0), n.get("code") or 0, 1 if n.get("day") else 0,
                            x10(n.get("wind")), x10(n.get("high")), x10(n.get("low")),
                            int(n.get("rain_chance") or 0), 0xFFFF if age is None else min(age // 60, 0xFFFE))
        value += bytes((len(place),)) + place + bytes((len(error),)) + error
        value += bytes((1 if w.cfg.get("auto_place") else 0,))   # place found automatically
        self.ble.gatts_write(self.h_weather, value)

    def write_wifi(self, notify):
        """Wi-Fi: state, reason, rssi, IP, SSID, scanning, scan results. Notified when it changes."""
        net = self.app.net
        state, reason = net.wifi_state()
        ip = bytes(int(p) for p in net.ip().split(".")) if state == 2 else b"\0\0\0\0"
        ssid = net.ssid.encode()[:32]
        value = struct.pack("<BBb4sB", state, reason, net.rssi() if state == 2 else 0, ip, len(ssid)) + ssid
        # bit 0 MQTT on, bit 1 MQTT connected, bit 2 online (internet reachable)
        mqtt = (1 if self.app.cfg["mqtt"]["enabled"] else 0) | (2 if net.mqtt_ok else 0) | (4 if self.app.online() else 0)
        value += bytes((1 if self.scanning else 0, mqtt, len(self.scan_results)))
        for name, rssi in self.scan_results:
            name = name.encode()[:32]
            value += bytes((len(name),)) + name + struct.pack("b", rssi)
        if value != self._wifi_value:
            self._wifi_value = value
            self.ble.gatts_write(self.h_wifi, value)
            if notify:
                self._notify(((self.h_wifi, value),))

    def write_calibration(self, notify=False):
        """Calibration (20 bytes): offset and the self-heating measurement's
        status, see docs/bluetooth.md."""
        app = self.app
        cal = app.selfcal

        def x100(value):
            return _NONE_I16 if value is None else int(round(value * 100))

        if cal:
            st = cal.status()
            age = 0xFFFFFFFF if st["result_age_s"] is None else st["result_age_s"]
            value = struct.pack("<hBBHHhhhIBB", x100(app.air.offset), 1 if st["auto"] else 0, cal.state,
                                st["elapsed_s"], st["cooldown_s"], x100(st["warm"]), x100(st["now"]),
                                x100(st["result"]), age, cal.reason, 0)
        else:
            value = struct.pack("<h", x100(app.air.offset))
        self.ble.gatts_write(self.h_calibration, value)
        if notify:
            self._notify(((self.h_calibration, value),))

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
        elif handle == self.h_time and len(value) in (7, 8):
            # u32 Unix time, i16 standard offset, u8 rule [, u8 source: 2 phone, 3 set by hand]
            unix, offset, dst = struct.unpack("<IhB", value[:7])
            app.set_time(unix, offset, dst, 3 if len(value) == 8 and value[7] == 3 else 2)
            self.write_time()
        elif handle == self.h_update and value and app.updater:
            # 1: check now. 2: install the available update (the user said yes). 3: dismiss.
            # 1 and 2 restart the board 1.5 s later (updater.py).
            # 4 / 5: install automatically on / off.
            if value[0] in (4, 5):
                app.cfg["update"]["auto"] = value[0] == 4
                app.save_settings()
            else:
                {1: app.updater.check, 2: app.updater.install, 3: app.updater.dismiss}.get(value[0], lambda: None)()
            self.write_update(notify=True)
        elif handle == self.h_weather and value and self.app.weather:
            # 1, len, name: set the place ("" = find automatically). 2 / 3: weather on / off. 4: refresh now.
            w = self.app.weather
            if value[0] == 1 and len(value) >= 2:
                w.set_place(value[2:2 + value[1]].decode())
            elif value[0] in (2, 3):
                w.cfg["enabled"] = value[0] == 2
                app.save_settings()
            elif value[0] == 4:
                w.refresh()
            self.write_weather()
        elif handle == self.h_wifi and value:
            # 1: scan. 2, len, SSID, len, password: connect. 3: back to config.json's
            # network. 4 / 5: MQTT on / off.
            if value[0] == 1:
                self.scanning = True
                self.write_wifi(notify=True)
            elif value[0] == 2 and len(value) >= 3:
                n = value[1]
                ssid = value[2:2 + n].decode()
                password = value[3 + n:3 + n + value[2 + n]].decode() if len(value) > 2 + n else ""
                app.set_wifi(ssid, password)
            elif value[0] == 3:
                app.forget_wifi()
            elif value[0] in (4, 5):
                app.set_mqtt(value[0] == 4)
            self.write_wifi(notify=True)
        elif handle == self.h_calibration:
            # 2 bytes: offset. 4 bytes: offset, auto (0/1), command (1 start, 2 cancel).
            if len(value) in (2, 4):
                offset = struct.unpack("<h", value[:2])[0] / 100
                try:
                    if offset != app.air.offset:
                        app.set_temperature_offset(offset)
                except ValueError as e:
                    print("Bluetooth:", e)
                if len(value) == 4 and app.selfcal:
                    if bool(value[2]) != app.cfg["sensor"]["auto_calibration"]:
                        app.cfg["sensor"]["auto_calibration"] = bool(value[2])
                        app.save_settings()
                    if value[3] == 1:
                        app.selfcal.start()
                    elif value[3] == 2:
                        app.selfcal.cancel()
            self.write_calibration(notify=True)
        elif handle == self.h_display:
            # A rejected write can't be refused over the air from MicroPython:
            # the old value is written back, and the app sees it on its next read.
            if len(value) in (5, 6, 7):
                _, mask, page_ms = struct.unpack("<BHH", value[:5])
                if len(value) == 7:
                    mask |= value[6] << 16
                cfg = app.cfg["display"]
                if len(value) >= 6:   # flags; a 5-byte write leaves the rotation alone
                    cfg["rotate"] = bool(value[5] & 1)
                    if app.display:
                        app.display.set_rotate(cfg["rotate"])
                # The mask has no order: keep the current order, append new pages.
                chosen = [p for p in cfg["pages"] if PAGE_BITS[p] & mask] + \
                    [p for p in _PAGE_ORDER if PAGE_BITS[p] & mask and p not in cfg["pages"]]
                if chosen and PAGE_MS_MIN <= page_ms <= PAGE_MS_MAX:
                    cfg["pages"], cfg["page_s"] = chosen, page_ms / 1000
                    if app.display:
                        app.display.set_pages(chosen)
                    app.save_settings()
                    print("Bluetooth: display", chosen, "every", page_ms, "ms, rotated:", cfg["rotate"])
            self.write_display()
