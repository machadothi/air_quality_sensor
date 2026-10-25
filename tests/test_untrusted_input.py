"""Data from the network can't take the board down (security review): MQTT
messages, and weather replies, which arrive over plain HTTP."""

import sys

import pytest


@pytest.fixture
def online_app(board, firmware, config, run):
    board.networks = {"Home": "pw"}
    config({"wifi": {"ssid": "Home", "password": "pw"}, "mqtt": {"server": "broker"}})
    sys.modules["umqtt.simple"].MQTTClient.broker_up = True
    a = firmware("app").App()
    run(a, 10)
    assert a.net.mqtt_ok
    return a


@pytest.mark.parametrize("message", [b"\xff\xfe not utf-8", b"/status" + b" " * 2000, b"/display {not json",
                                     b"/weather place " + "å".encode() * 100])
def test_bad_mqtt_requests_are_ignored(online_app, run, message):
    sys.modules["umqtt.simple"].MQTTClient.inbox.append(message)
    run(online_app, 2)
    assert online_app.net.mqtt_ok
    assert len(online_app.cfg["weather"].get("place") or "") <= 40


@pytest.mark.parametrize("error", [MemoryError("huge message"), IndexError("short packet"), OSError("reset")])
def test_broken_mqtt_traffic_drops_the_link_not_the_board(online_app, run, error):
    sys.modules["umqtt.simple"].MQTTClient.inbox.append(error)
    run(online_app, 1)
    assert not online_app.net.mqtt_ok   # dropped; reconnects later
    run(online_app, 20)
    assert online_app.net.mqtt_ok


class Reply:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def close(self):
        pass


GOOD = {"current": {"temperature_2m": 12.5, "apparent_temperature": 11, "relative_humidity_2m": 80,
                    "weather_code": 3, "wind_speed_10m": 4.2, "is_day": 1},
        "daily": {"temperature_2m_max": [14], "temperature_2m_min": [6], "precipitation_probability_max": [None]}}


def spoofed(**current):
    data = {"current": dict(GOOD["current"], **current), "daily": GOOD["daily"]}
    return data


@pytest.mark.parametrize("reply", [spoofed(temperature_2m="hot"), spoofed(relative_humidity_2m=1e9),
                                   spoofed(weather_code=None), {"current": {}}, [], "x"])
def test_spoofed_weather_is_rejected(online_app, monkeypatch, run, reply):
    w = online_app.weather
    w.cfg.update(latitude=59.3, longitude=18.0, place="Stockholm")
    monkeypatch.setattr(sys.modules["requests"], "get", lambda *a, **k: Reply(reply))
    w.refresh()
    run(online_app, 30)             # the display and Bluetooth keep going
    assert w.now is None and w.error


def test_good_weather_is_kept_and_shown(online_app, monkeypatch, run):
    w = online_app.weather
    w.cfg.update(latitude=59.3, longitude=18.0, place="Stockholm")
    monkeypatch.setattr(sys.modules["requests"], "get", lambda *a, **k: Reply(GOOD))
    w.refresh()
    run(online_app, 5)
    assert w.now["temperature"] == 12.5 and w.now["rain_chance"] == 0
    online_app.ble.write_weather()  # packs every value


@pytest.mark.parametrize("found", [{"status": "success", "city": "X", "lat": "north", "lon": 1},
                                   {"status": "success", "city": "X", "lat": 95, "lon": 1},
                                   {"status": "success"}])
def test_spoofed_location_is_rejected(online_app, monkeypatch, run, found):
    w = online_app.weather
    monkeypatch.setattr(sys.modules["requests"], "get", lambda *a, **k: Reply(found))
    w.set_place("auto")
    run(online_app, 2)
    assert w.cfg["latitude"] is None


def test_failed_location_lookups_are_spaced_out(online_app, monkeypatch, run):
    calls = []

    def get(*a, **k):
        calls.append(1)
        raise OSError("no internet")
    monkeypatch.setattr(sys.modules["requests"], "get", get)
    run(online_app, 600, step_ms=1000)   # 10 minutes: one try now, one after 5 minutes
    assert len(calls) <= 3
