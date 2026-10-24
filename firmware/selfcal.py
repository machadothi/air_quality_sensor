# Automatic temperature offset ("self-heating measurement"), ESP32 only.
#
# The AHT21 shares its board with the ENS160, and both sit next to the ESP32
# and the display: it reads 1-3 °C high. Neither chip can tell how much. This
# measures it by switching the whole board off:
#   1. warm:  the AHT21's uncorrected temperature, averaged over the last minute,
#             with everything running normally;
#   2. off:   the ENS160 goes to sleep (heaters off), the display off, MQTT
#             signs off, and the ESP32 goes into deep sleep for cooldown_min:
#             no CPU, Wi-Fi or Bluetooth heat at all;
#   3. cool:  the very first AHT21 reading after waking, taken by wake() from
#             main.py before Wi-Fi, Bluetooth or the app start;
#      offset = cool - warm (negative), applied and stored when the app starts;
#   4. the ENS160 measures again (3-minute warm-up).
# A rise instead of a fall means the room changed during the run: rejected. If
# the board was reset or powered off meanwhile, the cooling time is unknown:
# rejected as interrupted. While it sleeps the board sends nothing (no BTHome,
# no MQTT: Home Assistant shows it unavailable for those minutes).
#
# Started from the app (Calibration characteristic), over MQTT (/calibrate start),
# or automatically when "auto" is on: once a night at calibration_hour (local
# time, when the board knows the time), else every calibration_interval_h hours;
# only after the ENS160 has run long enough for the board to be fully warm.
import json
import time

from micropython import const

IDLE = const(0)
COOLING = const(2)   # about to switch off (the app sees this before the link drops)
DONE = const(3)
FAILED = const(4)
STATE_NAMES = {IDLE: "idle", COOLING: "cooling", DONE: "done", FAILED: "failed"}

# Why a run failed
NO_SENSOR = const(1)      # AHT21 or ENS160 not answering
ROOM_CHANGED = const(2)   # the temperature rose while cooling
CANCELLED = const(3)
TOO_LARGE = const(4)      # more than 10 °C: not self-heating
INTERRUPTED = const(5)    # reset or power-off during the sleep
REASONS = {NO_SENSOR: "sensor not answering", ROOM_CHANGED: "room temperature changed",
           CANCELLED: "cancelled", TOO_LARGE: "result out of range", INTERRUPTED: "interrupted (reset or power-off)"}

RUN_FILE = "/selfcal.json"   # survives the deep sleep: the warm reading, then the outcome
_SAMPLE_MS = const(10000)    # one temperature sample every 10 s, for the warm average
_SAMPLES = const(6)          # the last minute
_SLEEP_DELAY_MS = const(1500)   # let the app and MQTT hear "cooling" first
_WARM_FOR_S = const(3600)    # automatic runs: the ENS160 must have run this long
_AHT = const(0x38)


def _judge(warm, cool):
    """(result, reason): the offset, or None and why not."""
    offset = cool - warm
    if offset > 0.2:
        return None, ROOM_CHANGED
    if offset < -10:
        return None, TOO_LARGE
    return round(offset, 1), 0


def _read_aht(i2c):
    """One AHT21 temperature (°C, uncorrected), or None."""
    from sensors import _crc8
    if not i2c.readfrom(_AHT, 1)[0] & 0x08:   # not calibrated yet
        i2c.writeto(_AHT, b"\xbe\x08\x00")
        time.sleep_ms(10)
    for _ in range(3):
        i2c.writeto(_AHT, b"\xac\x33\x00")
        time.sleep_ms(80)
        d = i2c.readfrom(_AHT, 7)
        if not d[0] & 0x80 and _crc8(d) == d[6]:
            return ((d[3] & 0x0F) << 16 | d[4] << 8 | d[5]) * 200 / 1048576 - 50
        time.sleep_ms(50)
    return None


def wake():
    """main.py, first thing after starting: if a measurement was asleep, take
    the cool reading now, before anything warms the board."""
    import machine
    try:
        with open(RUN_FILE) as f:
            run = json.load(f)
    except (OSError, ValueError):
        return
    if "warm" not in run or "cool" in run or "reason" in run:
        return   # nothing pending (or already measured)
    if machine.reset_cause() != machine.DEEPSLEEP_RESET:
        run["reason"] = INTERRUPTED
    else:
        try:
            pins = {"i2c_scl": 22, "i2c_sda": 21}
            try:
                with open("config.json") as f:
                    pins.update(json.load(f).get("pins", {}).get("esp32", {}))
            except (OSError, ValueError):
                pass
            i2c = machine.I2C(0, scl=machine.Pin(pins["i2c_scl"]), sda=machine.Pin(pins["i2c_sda"]), freq=400000)
            cool = _read_aht(i2c)
        except OSError:
            cool = None
        if cool is None:
            run["reason"] = NO_SENSOR
        else:
            run["cool"] = cool
            run["result"], run["reason"] = _judge(run["warm"], cool)
    with open(RUN_FILE, "w") as f:
        json.dump(run, f)
    print("Self-heating measurement: woke up, cool %s °C" % run.get("cool"))


class SelfCalibration:
    def __init__(self, app):
        self.app = app
        self.state = IDLE
        self.reason = 0
        self.warm = self.cool = None
        self.result = app.cfg["sensor"].get("last_result")   # survives restarts (settings.json)
        self.result_at = None     # ticks of the last result (since this start)
        if self.result is not None:
            self.state = DONE
        self.started = 0
        self.samples = []         # uncorrected temperatures, newest last
        self._next_sample = time.ticks_ms()
        self._ens_since = time.ticks_ms()   # since when the ENS160 runs undisturbed
        self._night_done = None             # day of the year of the last nightly run
        self._sleep_at = None
        self._finish_run()

    @property
    def cfg(self):
        return self.app.cfg["sensor"]

    @property
    def running(self):
        return self.state == COOLING

    def elapsed_s(self):
        return time.ticks_diff(time.ticks_ms(), self.started) // 1000 if self.running else 0

    def _finish_run(self):
        """After the deep sleep: apply what wake() measured."""
        import os
        try:
            with open(RUN_FILE) as f:
                run = json.load(f)
            os.remove(RUN_FILE)
        except (OSError, ValueError):
            return
        self.warm, self.cool = run.get("warm"), run.get("cool")
        if run.get("result") is None:
            self._fail(run.get("reason") or INTERRUPTED)
            return
        self.result = self.cfg["last_result"] = run["result"]   # app.selfcal isn't set yet: keep it in cfg
        self.result_at = time.ticks_ms()
        self.state = DONE
        print("Self-heating measurement: warm %.2f °C, cool %.2f °C, offset %.1f °C" % (self.warm, self.cool, self.result))
        self.app.set_temperature_offset(self.result)

    def _mean(self, n):
        last = self.samples[-n:]
        return sum(last) / len(last) if last else None

    def start(self):
        """Begin a measurement: the board switches off for cooldown_min, 1.5 s
        from now. False if one is starting already or a sensor is missing."""
        air = self.app.air
        if self.running:
            return False
        if not (air.has_air and air.has_climate) or air.raw_temperature is None:
            self._fail(NO_SENSOR)
            return False
        self.warm = self._mean(_SAMPLES) if self.samples else air.raw_temperature   # last minute
        self.cool = None
        self.started = time.ticks_ms()
        self.state = COOLING
        self.reason = 0
        self._sleep_at = time.ticks_add(self.started, _SLEEP_DELAY_MS)
        print("Self-heating measurement: warm %.2f °C, switching off for %d min" % (self.warm, self.cfg["cooldown_min"]))
        return True

    def cancel(self):
        if self.running:
            self._sleep_at = None
            self._ens_since = time.ticks_ms()
            self._fail(CANCELLED)

    def _fail(self, reason):
        self.state, self.reason = FAILED, reason
        print("Self-heating measurement failed:", REASONS[reason])

    def _switch_off(self):
        """Everything that heats goes off, then the ESP32 sleeps for cooldown_min."""
        import machine
        app = self.app
        with open(RUN_FILE, "w") as f:
            json.dump({"warm": self.warm}, f)
        try:
            app.air.pause_air()                  # ENS160 heaters off (it stays powered)
        except OSError:
            pass
        machine.RTC().memory(b"")                # the ENS160 isn't "still running" after waking
        if app.display:
            try:
                app.display.splash("Calibrating: off for %d min" % self.cfg["cooldown_min"], None, "Self-heating")
                time.sleep_ms(1500)
                app.display.oled.poweroff()
            except OSError:
                pass
        app.net.stop_mqtt()                      # Home Assistant: offline, not stale
        print("Self-heating measurement: deep sleep")
        time.sleep_ms(100)
        machine.deepsleep(self.cfg["cooldown_min"] * 60 * 1000)

    def poll(self):
        now = time.ticks_ms()
        air = self.app.air
        if time.ticks_diff(now, self._next_sample) >= 0:
            self._next_sample = time.ticks_add(now, _SAMPLE_MS)
            if air.raw_temperature is not None:
                self.samples.append(air.raw_temperature)
                if len(self.samples) > _SAMPLES:
                    self.samples.pop(0)
        if self.running:
            if self._sleep_at is not None and time.ticks_diff(now, self._sleep_at) >= 0:
                self._sleep_at = None
                self._switch_off()
        elif self.cfg["auto_calibration"]:
            local = self.app.clock.local() if self.app.clock else None
            if local:   # the board knows the time: at night, once
                due = local[3] == self.cfg["calibration_hour"] and self._night_done != local[7]
            else:
                since = self.result_at if self.result_at is not None else self._ens_since
                due = time.ticks_diff(now, since) // 1000 >= self.cfg["calibration_interval_h"] * 3600
            warm = time.ticks_diff(now, self._ens_since) // 1000 >= _WARM_FOR_S
            if due and warm and air.valid:
                print("Self-heating measurement: automatic run")
                if local:
                    self._night_done = local[7]
                self.start()

    def status(self):
        """For MQTT (/calibrate) and the app."""
        age = None if self.result_at is None else time.ticks_diff(time.ticks_ms(), self.result_at) // 1000
        return {"state": STATE_NAMES[self.state], "reason": REASONS.get(self.reason),
                "auto": self.cfg["auto_calibration"], "elapsed_s": self.elapsed_s(),
                "cooldown_s": self.cfg["cooldown_min"] * 60, "warm": self.warm,
                "now": self.app.air.raw_temperature, "cool": self.cool, "result": self.result,
                "result_age_s": age, "offset": self.app.air.offset}
