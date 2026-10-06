# Air monitor: reads the ENS160 + AHT21 sensors, shows them on the OLED and
# publishes them over MQTT. main.py calls run().
#
# One loop does everything, each job when it is due (App.loop). Nothing waits
# more than a few milliseconds, so the display stays smooth and MQTT requests
# are answered right away.
#
# RAM is the tight resource on the ESP8266 (~36 KB for everything): rarely
# used code (commands.py, home_assistant.py) is only loaded when needed, and
# defaults only exist while the configuration loads. See docs/architecture.md.
import gc
import json
import sys
import time

import machine

import sensors
from net import Net

CONFIG_FILE = "config.json"
# Display choices made over MQTT (/display); they override config.json. Kept
# apart so config.json, with the passwords, is never rewritten by the board.
SETTINGS_FILE = "settings.json"
# The chip this runs on: "esp8266" or "esp32". Detected, so the same
# config.json works on either board.
PLATFORM = sys.platform

# Display pages, in their default order. The ESP32 has the extra ones (ui_more.py).
PAGE_NAMES = ("air", "eco2", "tvoc", "temperature", "humidity") + (
    ("dewpoint", "sensor", "system", "clock") if PLATFORM == "esp32" else ())

# Default pins per board; config.json "pins" overrides them.
# display_reset: the OLED's RES pin, if wired (the 7-pin 2.42" modules need a
# reset pulse at start-up); None when the module resets itself (4-pin modules).
DEFAULT_PINS = {
    "esp8266": {"i2c_scl": 5, "i2c_sda": 4, "display_reset": None},
    "esp32": {"i2c_scl": 22, "i2c_sda": 21, "display_reset": 4},
}

OFFSET_MIN = -10         # allowed temperature offset, °C
OFFSET_MAX = 10

_REFRESH_MS = 1000       # redraw the shown page
_HISTORY_MS = 60000      # one chart point a minute
_MEMORY_MS = 10000       # track the lowest free RAM
_WATCHDOG_MS = 120000    # restart if the loop stalls this long
_BOOT_WIFI_WAIT_MS = 8000

_display = None          # for the error screen in run()


def load_config():
    """config.json, completed with defaults, then settings.json on top."""
    defaults = {
        "mqtt": {
            "enabled": True,                        # False: no MQTT at all (switch in the app)
            "port": 0,                              # 0 = 1883
            "topic_state": "esp/air_quality_sensor",
            "publish_s": 60,                        # readings are averaged over this time
            "home_assistant_discovery": False,
            "device_name": "Air Monitor",
        },
        "time": {                                   # ESP32: set by the app from the phone's zone
            "offset_min": 0,                        # standard offset from UTC, minutes
            "dst": 0,                               # summer time rule: 0 none, 1 EU, 2 US
        },
        "sensor": {
            "temperature_offset": 0.0,              # °C added to the AHT21 reading
            "calibration_hour": 3,                  # nightly automatic measurement, local time
            "auto_calibration": False,              # measure the offset automatically (selfcal.py)
            "calibration_interval_h": 24,
            "cooldown_min": 20,                     # longest cooling period of a measurement
        },
        "bluetooth": {                              # ESP32 only, see ble.py
            "enabled": True,
            "bthome": True,                         # broadcast readings for Home Assistant
            "name": "",                             # "" = Air-Monitor-<last 4 hex digits of the MAC>
        },
        "display": {
            "enabled": True,
            "address": 0x3C,
            "page_s": 5,                            # time per page
            "contrast": 255,                        # brightness 0-255 (max)
            "rotate": False,                        # True = upside down
            "pages": list(PAGE_NAMES),
        },
    }
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    # "esp" in older config files is ignored: the board is detected (PLATFORM).
    pins = DEFAULT_PINS[PLATFORM].copy()
    pins.update(cfg.get("pins", {}).get(PLATFORM, {}))
    cfg["pins"] = pins
    for section, values in defaults.items():
        if isinstance(values, dict):
            cfg.setdefault(section, {})
            for key, value in values.items():
                cfg[section].setdefault(key, value)
        else:
            cfg.setdefault(section, values)
    if cfg.get("devices", {}).get("display") is False:   # the old firmware's switch
        cfg["display"]["enabled"] = False
    cfg["wifi_from_app"] = False
    cfg["config_wifi"] = dict(cfg["wifi"])   # to go back to after "forget"
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
        if saved.get("wifi"):   # a network chosen in the app wins over config.json
            cfg["wifi"].update(saved["wifi"])
            cfg["wifi_from_app"] = True
        cfg["time"].update(saved.get("time", {}))
        if "mqtt_enabled" in saved:
            cfg["mqtt"]["enabled"] = saved["mqtt_enabled"]
        cfg["display"].update(saved.get("display", {}))
        cfg["bluetooth"].update(saved.get("bluetooth", {}))
        cfg["sensor"].update(saved.get("sensor", {}))
    except (OSError, ValueError, AttributeError):   # nothing saved yet, or a damaged file
        pass
    return cfg


def make_i2c(cfg):
    pins = cfg["pins"]
    scl, sda = machine.Pin(pins["i2c_scl"]), machine.Pin(pins["i2c_sda"])
    if PLATFORM == "esp8266":   # no hardware I2C on the ESP8266
        return machine.SoftI2C(scl=scl, sda=sda, freq=400000)
    return machine.I2C(0, scl=scl, sda=sda, freq=400000)


def _mean(sums, i):
    return sums[i] / sums[i + 1] if sums[i + 1] else None


def _round(value, decimals):
    return None if value is None else round(value, decimals) if decimals else int(value + 0.5)


class App:
    def __init__(self):
        global _display
        self.cfg = cfg = load_config()
        # Uptime from the tick counter: time.time() jumps when the clock gets set.
        self._uptime_ms = 0
        self._uptime_tick = time.ticks_ms()
        self.reboot_at = None
        self.last_feed = time.ticks_ms()
        if PLATFORM == "esp8266":
            machine.freq(160000000)   # smoother display animation (the ESP32 already runs at 160 MHz)
        i2c = make_i2c(cfg)

        # The display first: its two 1 KB buffers need RAM that isn't fragmented yet.
        self.display = self.history = self.ble = None
        if cfg["display"]["enabled"]:
            try:
                import ui
                if PLATFORM == "esp32":
                    import ui_more   # extra pages; must be known before the Display picks its pages
                    ui_more.register(ui, self)
                self.display = _display = ui.Display(i2c, cfg["display"], cfg["pins"]["display_reset"])
                self.history = ui.History()
                self.display.splash("Starting sensors", 0.1)
            except OSError as e:
                print("Display not found:", e)

        self.air = sensors.AirSensor(i2c, cfg["sensor"]["temperature_offset"])
        self.net = Net(cfg["wifi"], cfg["mqtt"], self.on_request)
        self.ble = self.selfcal = self.clock = None
        if PLATFORM == "esp32":
            import clock
            import selfcal
            self.clock = clock.Clock(cfg["time"])
            self.selfcal = selfcal.SelfCalibration(self)
        if PLATFORM == "esp32" and cfg["bluetooth"]["enabled"]:
            import ble
            self.ble = ble.Ble(self)
        gc.collect()
        self.min_free = gc.mem_free()

    def save_settings(self):
        """Store what was changed over MQTT or Bluetooth (display pages,
        timing and rotation, Bluetooth name, temperature offset) in
        settings.json; config.json stays untouched."""
        cfg = self.cfg
        display, bt = cfg["display"], cfg["bluetooth"]
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"wifi": cfg["wifi"] if cfg["wifi_from_app"] else None,
                       "time": cfg["time"],
                       "mqtt_enabled": cfg["mqtt"]["enabled"],
                       "display": {"pages": display["pages"], "page_s": display["page_s"],
                                   "rotate": display["rotate"]},
                       "bluetooth": {"name": bt["name"]},
                       "sensor": {"temperature_offset": self.air.offset,
                                  "auto_calibration": self.cfg["sensor"]["auto_calibration"],
                                  "last_result": self.selfcal.result if self.selfcal else None}}, f)

    def set_wifi(self, ssid, password):
        """A network chosen in the app; stored in settings.json."""
        self.cfg["wifi"] = {"ssid": ssid, "password": password}
        self.cfg["wifi_from_app"] = True
        self.save_settings()
        self.net.set_wifi(ssid, password)

    def set_mqtt(self, enabled):
        """MQTT on/off (from the app); stored in settings.json."""
        self.cfg["mqtt"]["enabled"] = enabled
        self.save_settings()
        if not enabled:
            self.net.stop_mqtt()
        print("MQTT", "on" if enabled else "off")

    def forget_wifi(self):
        """Back to the network in config.json."""
        wifi = self.cfg["config_wifi"]
        self.cfg["wifi"] = dict(wifi)
        self.cfg["wifi_from_app"] = False
        self.save_settings()
        self.net.set_wifi(wifi["ssid"], wifi["password"])

    def set_time(self, unix_utc, offset_min, dst):
        """Time and zone from the phone (Bluetooth)."""
        self.cfg["time"].update({"offset_min": offset_min, "dst": dst})
        self.save_settings()
        if self.clock:
            self.clock.set_utc(unix_utc, 2)

    def set_temperature_offset(self, offset):
        """°C added to the AHT21's temperature (it reads high: the ENS160 next to
        it heats the board). Humidity and the ENS160's compensation follow."""
        if not OFFSET_MIN <= offset <= OFFSET_MAX:
            raise ValueError("offset must be %d to %d °C" % (OFFSET_MIN, OFFSET_MAX))
        self.air.offset = self.cfg["sensor"]["temperature_offset"] = round(offset, 2)
        self.save_settings()
        print("Temperature offset:", self.air.offset, "°C")

    def factory_reset(self):
        """Forget settings.json (back to config.json) and restart."""
        import os
        try:
            os.remove(SETTINGS_FILE)
        except OSError:
            pass
        print("Factory reset")
        self.reboot_at = time.ticks_add(time.ticks_ms(), 500)

    def uptime_s(self):
        return (self._uptime_ms + time.ticks_diff(time.ticks_ms(), self._uptime_tick)) // 1000

    def system_info(self):
        """The board itself: shown in the app (Bluetooth), /status and the system page."""
        net = self.net
        info = {
            "uptime_s": self.uptime_s(),
            "free_ram": gc.mem_free(),
            "cpu_mhz": machine.freq() // 1000000,
            "reset_cause": machine.reset_cause(),
            "micropython": sys.implementation.version[:3],
            "wifi": net.wifi_ok,
            "wifi_rssi": net.rssi() if net.wifi_ok else None,
            "ip": net.ip() if net.wifi_ok else None,
            "mqtt": net.mqtt_ok,
            "bluetooth": self.ble is not None and self.ble.connection is not None,
            "chip_temperature": None,
        }
        if PLATFORM == "esp32":
            import esp32
            # Die temperature, uncalibrated: runs well above room temperature.
            info["chip_temperature"] = (esp32.raw_temperature() - 32) / 1.8
        if self.clock:
            import clock
            t = self.clock.local()
            info["time"] = None if t is None else "%04d-%02d-%02d %02d:%02d" % t[:5]
            info["time_source"] = clock.SOURCES[self.clock.source]
        return info

    def sensor_state(self):
        air = self.air
        if air.paused:
            return "calibrating"
        return sensors.VALIDITY_NAMES[air.validity] if air.validity is not None else "no sensor"

    def state_message(self, sums=None):
        """The JSON published on topic_state: averages of sums (from
        air.take_sums()), or the latest readings without. Keys match the old
        firmware's, plus aqi and state; eco2/tvoc/aqi are null until valid."""
        air = self.air
        valid = air.valid
        if sums:
            values = [_mean(sums, i) for i in (0, 2, 4, 6)]
            values = [values[0] if air.has_climate else None, values[1] if air.has_climate else None,
                      values[2] if valid else None, values[3] if valid else None]
        else:
            values = [air.temperature, air.humidity, air.eco2 if valid else None, air.tvoc if valid else None]
        return {
            "temperature": _round(values[0], 1),
            "humidity": _round(values[1], 1),
            "dew_point": _round(sensors.dew_point(values[0], values[1]), 1),
            "absolute_humidity": _round(sensors.absolute_humidity(values[0], values[1]), 1),
            "eco2": _round(values[2], 0),
            "tvoc": _round(values[3], 0),
            "aqi": air.aqi if valid else None,
            "state": self.sensor_state(),
            "status": air.status,   # raw ENS160 status register
        }

    def on_request(self, text):
        """An MQTT request; commands.py answers it, loaded just for that."""
        gc.collect()   # loading a module needs a few KB in one piece
        try:
            import commands
            return commands.handle(self, text)
        except Exception as e:   # a bad request must never take the board down
            sys.print_exception(e)
            return {"error": "%s: %s" % (type(e).__name__, e)}
        finally:
            sys.modules.pop("commands", None)
            gc.collect()

    def connect(self):
        """Start screen while Wi-Fi connects; stop waiting after a few seconds."""
        display, net = self.display, self.net
        start = time.ticks_ms()
        while not net.wifi_ok and time.ticks_diff(time.ticks_ms(), start) < _BOOT_WIFI_WAIT_MS:
            if display:
                display.splash("Connecting to Wi-Fi",
                               0.2 + 0.6 * time.ticks_diff(time.ticks_ms(), start) / _BOOT_WIFI_WAIT_MS)
            self.air.update()
            time.sleep_ms(200)
        if display:
            display.splash("Connecting to MQTT" if net.wifi_ok else "No Wi-Fi yet", 0.9)
        net.poll()

    def _watchdog(self, _):
        """Timer callback: restart if the loop stopped, e.g. on a hung network
        call. (The ESP8266's hardware WDT can't be given a timeout this long.)"""
        if time.ticks_diff(time.ticks_ms(), self.last_feed) > _WATCHDOG_MS:
            print("Watchdog: main loop stuck, restarting")
            machine.reset()

    def loop(self):
        air, net, display, history = self.air, self.net, self.display, self.history
        cfg = self.cfg
        now = time.ticks_ms()
        next_publish = next_refresh = next_memory = now   # publish as soon as MQTT is up
        next_history = time.ticks_add(now, 10000)          # first chart point soon
        next_page = time.ticks_add(now, int(cfg["display"]["page_s"] * 1000))
        # The ESP8266 has virtual timers (-1); the ESP32 has hardware timer 0.
        timer = machine.Timer(-1 if PLATFORM == "esp8266" else 0)
        timer.init(period=5000, mode=machine.Timer.PERIODIC, callback=self._watchdog)
        print("Running")
        try:
            while True:
                self.last_feed = now
                self._uptime_ms += time.ticks_diff(now, self._uptime_tick)
                self._uptime_tick = now
                if self.clock:
                    self.clock.poll(net.wifi_ok)
                air.update()
                net.poll()
                if self.selfcal:
                    self.selfcal.poll()
                if self.ble:
                    self.ble.poll()
                now = time.ticks_ms()

                if net.mqtt_ok and time.ticks_diff(now, next_publish) >= 0:
                    net.publish_state(self.state_message(air.take_sums()))
                    next_publish = time.ticks_add(now, cfg["mqtt"]["publish_s"] * 1000)

                if history and time.ticks_diff(now, next_history) >= 0:
                    history.push(air)
                    next_history = time.ticks_add(now, _HISTORY_MS)

                if display:
                    if time.ticks_diff(now, next_page) >= 0:
                        display.next_page(air, net, history)
                        now = time.ticks_ms()
                        next_page = time.ticks_add(now, int(cfg["display"]["page_s"] * 1000))
                        next_refresh = time.ticks_add(now, _REFRESH_MS)
                    elif time.ticks_diff(now, next_refresh) >= 0:
                        display.refresh(air, net, history)
                        next_refresh = time.ticks_add(now, _REFRESH_MS)

                if time.ticks_diff(now, next_memory) >= 0:
                    gc.collect()
                    self.min_free = min(self.min_free, gc.mem_free())
                    next_memory = time.ticks_add(now, _MEMORY_MS)

                if self.reboot_at is not None and time.ticks_diff(now, self.reboot_at) >= 0:
                    machine.reset()

                time.sleep_ms(20)
        finally:
            timer.deinit()


def run():
    """Run the monitor; on a crash show it, then restart the board."""
    try:
        app = App()
        app.connect()
        app.loop()
    except KeyboardInterrupt:   # Ctrl+C from mpremote: stop, back to the REPL
        print("Stopped")
        raise
    except Exception as e:
        sys.print_exception(e)
        if _display:
            try:
                _display.splash(type(e).__name__ + ", restarting", None, "Error")
            except Exception:
                pass
        time.sleep(10)
        machine.reset()
