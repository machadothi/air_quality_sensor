# Automatic temperature offset ("self-heating measurement"), ESP32 only.
#
# The AHT21 shares its board with the ENS160, whose heaters warm it: it reads
# 1-3 °C high. Neither chip can tell how much. This measures it:
#   1. warm:  the AHT21's uncorrected temperature, averaged over the last minute,
#             with the ENS160 measuring normally;
#   2. cool:  the ENS160 goes to sleep (heaters off) until the temperature stops
#             falling: less than STABLE_C change in 2 minutes, after at least
#             MIN_COOL_S, at most cooldown_min;
#   3. cool temperature averaged over the last minute;
#      offset = cool - warm (negative), applied and stored;
#   4. the ENS160 measures again (3-minute warm-up).
# A rise instead of a fall means the room changed during the run: rejected.
#
# Started from the app (Calibration characteristic), over MQTT (/calibrate start),
# or automatically every interval_h hours when "auto" is on, but only after the
# ENS160 has run long enough for the board to be fully warm (WARM_FOR_S).
import time

from micropython import const

IDLE = const(0)
COOLING = const(2)
DONE = const(3)
FAILED = const(4)
STATE_NAMES = {IDLE: "idle", COOLING: "cooling", DONE: "done", FAILED: "failed"}

# Why a run failed
NO_SENSOR = const(1)      # AHT21 or ENS160 not answering
ROOM_CHANGED = const(2)   # the temperature rose while cooling
CANCELLED = const(3)
TOO_LARGE = const(4)      # more than 10 °C: not self-heating
REASONS = {NO_SENSOR: "sensor not answering", ROOM_CHANGED: "room temperature changed",
           CANCELLED: "cancelled", TOO_LARGE: "result out of range"}

_SAMPLE_MS = const(10000)   # one temperature sample every 10 s
_SAMPLES = const(13)        # two minutes of them (+1)
_MIN_COOL_S = const(300)
_STABLE_C = 0.05
_WARM_FOR_S = const(3600)   # automatic runs: the ENS160 must have run this long


class SelfCalibration:
    def __init__(self, app):
        self.app = app
        self.state = IDLE
        self.reason = 0
        self.warm = self.cool = self.result = None
        self.result_at = None     # ticks of the last result
        self.started = 0
        self.samples = []         # uncorrected temperatures, newest last
        self._next_sample = time.ticks_ms()
        self._ens_since = time.ticks_ms()   # since when the ENS160 runs undisturbed

    @property
    def cfg(self):
        return self.app.cfg["sensor"]

    @property
    def running(self):
        return self.state == COOLING

    def elapsed_s(self):
        return time.ticks_diff(time.ticks_ms(), self.started) // 1000 if self.running else 0

    def _mean(self, n):
        last = self.samples[-n:]
        return sum(last) / len(last) if last else None

    def start(self):
        """Begin a measurement; False if one is running or a sensor is missing."""
        air = self.app.air
        if self.running:
            return False
        if not (air.has_air and air.has_climate) or air.raw_temperature is None:
            self._fail(NO_SENSOR)
            return False
        self.warm = self._mean(6) if self.samples else air.raw_temperature   # last minute
        self.cool = None
        self.samples = []
        self.started = time.ticks_ms()
        self.state = COOLING
        self.reason = 0
        air.pause_air()
        print("Self-heating measurement: warm %.2f °C, cooling down" % self.warm)
        return True

    def cancel(self):
        if self.running:
            self.app.air.resume_air()
            self._ens_since = time.ticks_ms()
            self._fail(CANCELLED)

    def _fail(self, reason):
        self.state, self.reason = FAILED, reason
        print("Self-heating measurement failed:", REASONS[reason])

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
            self._poll_cooling(air)
        elif self.cfg["auto_calibration"]:
            since = self.result_at if self.result_at is not None else self._ens_since
            due = time.ticks_diff(now, since) // 1000 >= self.cfg["calibration_interval_h"] * 3600
            warm = time.ticks_diff(now, self._ens_since) // 1000 >= _WARM_FOR_S
            if due and warm and air.valid:
                print("Self-heating measurement: automatic run")
                self.start()

    def _poll_cooling(self, air):
        elapsed = self.elapsed_s()
        limit = self.cfg["cooldown_min"] * 60
        air.pause_left = (max(0, limit - elapsed), limit)
        if not air.has_climate:
            air.resume_air()
            self._ens_since = time.ticks_ms()
            self._fail(NO_SENSOR)
            return
        if elapsed < _MIN_COOL_S and elapsed < limit:
            return
        settled = len(self.samples) >= _SAMPLES and abs(self.samples[-1] - self.samples[0]) < _STABLE_C
        if not settled and elapsed < limit:
            return
        self.cool = self._mean(6)
        air.resume_air()
        self._ens_since = time.ticks_ms()
        offset = self.cool - self.warm
        if offset > 0.2:
            self._fail(ROOM_CHANGED)
        elif offset < -10:
            self._fail(TOO_LARGE)
        else:
            self.result = round(offset, 1)
            self.result_at = time.ticks_ms()
            self.state = DONE
            print("Self-heating measurement: cool %.2f °C, offset %.1f °C" % (self.cool, self.result))
            self.app.set_temperature_offset(self.result)

    def status(self):
        """For MQTT (/calibrate) and the app."""
        age = None if self.result_at is None else time.ticks_diff(time.ticks_ms(), self.result_at) // 1000
        return {"state": STATE_NAMES[self.state], "reason": REASONS.get(self.reason),
                "auto": self.cfg["auto_calibration"], "elapsed_s": self.elapsed_s(),
                "cooldown_s": self.cfg["cooldown_min"] * 60, "warm": self.warm,
                "now": self.app.air.raw_temperature, "cool": self.cool, "result": self.result,
                "result_age_s": age, "offset": self.app.air.offset}
