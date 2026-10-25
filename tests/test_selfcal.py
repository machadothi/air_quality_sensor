"""Self-heating measurement: the whole board switches off (deep sleep) for
cooldown_min; the first AHT21 reading after waking, against the warm reading
before, is the offset."""

import json

import pytest

import fakes


@pytest.fixture
def warm_app(board, firmware, monkeypatch):
    """A running board whose sensors read 24.0 °C (uncorrected), ENS160 working."""
    selfcal = firmware("selfcal")
    monkeypatch.setattr(selfcal, "RUN_FILE", "selfcal.json")   # in the fake flash
    a = firmware("app").App()
    air = a.air
    air.has_air = air.has_climate = True
    air.raw_temperature = 24.0
    monkeypatch.setattr(air, "pause_air", lambda: setattr(air, "paused", True))
    a.selfcal.samples = [24.1, 24.0, 23.9, 24.0, 24.0, 24.0]
    return a


def switch_off(app, run):
    assert app.selfcal.start()
    with pytest.raises(fakes.DeepSleep) as sleep:
        run(app, 5)
    return sleep.value.ms


def wake_up(board, firmware, cool, cause=4):
    board.reset_cause = cause               # 4 = DEEPSLEEP_RESET
    board.i2c_devices[0x38] = aht = fakes.FakeAHT21(cool)
    firmware("selfcal").wake()
    return aht


def test_switches_the_whole_board_off(board, warm_app, run):
    ms = switch_off(warm_app, run)
    assert ms == 5 * 60 * 1000
    assert warm_app.air.paused and not warm_app.net.mqtt_ok
    assert json.load(open("selfcal.json")) == {"warm": pytest.approx(24.0)}


def test_first_reading_after_waking_is_the_offset(board, firmware, warm_app, run):
    switch_off(warm_app, run)
    aht = wake_up(board, firmware, cool=21.8)
    assert aht.measurements == 1            # the very first reading, nothing else
    a = firmware("app").App()               # the app starts after wake()
    assert a.selfcal.state == 3 and a.selfcal.result == -2.2
    assert a.air.offset == -2.2
    saved = json.load(open("settings.json"))["sensor"]
    assert saved["temperature_offset"] == -2.2 and saved["last_result"] == -2.2


def test_reset_during_the_sleep_is_rejected(board, firmware, warm_app, run):
    switch_off(warm_app, run)
    wake_up(board, firmware, cool=21.8, cause=1)   # power-on, not the timer
    a = firmware("app").App()
    assert a.selfcal.state == 4 and a.selfcal.status()["reason"].startswith("interrupted")
    assert a.air.offset == 0.0


def test_warmer_room_is_rejected(board, firmware, warm_app, run):
    switch_off(warm_app, run)
    wake_up(board, firmware, cool=25.0)
    a = firmware("app").App()
    assert a.selfcal.state == 4 and a.selfcal.status()["reason"] == "room temperature changed"


def test_cancel_before_switching_off(board, warm_app, run):
    warm_app.selfcal.start()
    warm_app.selfcal.cancel()
    run(warm_app, 5)                         # no deep sleep
    assert warm_app.selfcal.state == 4


def test_needs_both_sensors(board, warm_app):
    warm_app.air.has_air = False
    assert not warm_app.selfcal.start()


def test_wake_without_a_measurement_does_nothing(board, firmware):
    board.reset_cause = 4
    firmware("selfcal").wake()               # no selfcal.json: plain deep-sleep wake
