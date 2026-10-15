"""The board must run without Wi-Fi, a network, a broker or even a config.json;
only the internet features wait (PR #1 and the security review)."""

import json

import pytest

import fakes


def test_starts_without_config(board, firmware):
    a = firmware("app").App()
    assert a.net.ssid == "" and not a.net.wifi_ok and not a.net.mqtt_ok


@pytest.mark.parametrize("content", ['{"sensor": {"temperature_offset": -1.5}}', "{oops", ""])
def test_starts_with_partial_or_broken_config(board, firmware, content):
    with open("config.json", "w") as f:
        f.write(content)
    a = firmware("app").App()
    assert a.cfg["mqtt"]["server"] == ""
    if "sensor" in content:
        assert a.cfg["sensor"]["temperature_offset"] == -1.5


def test_keeps_running_when_the_network_is_gone(board, firmware, config, run):
    config({"wifi": {"ssid": "Gone", "password": "pw"}})
    a = firmware("app").App()
    run(a, 180, step_ms=1000)   # the old code crashed after 30 s ("Wifi Internal Error")
    assert a.net.wifi_state() == (3, 2)   # failed: network not found


def test_choose_another_network_from_the_app(board, firmware, config, run):
    config({"wifi": {"ssid": "Gone", "password": "pw"}})
    board.networks = {"Home2": "secret"}
    a = firmware("app").App()
    run(a, 40)
    ble = board.ble
    ble.phone_writes(a.ble.h_wifi, b"\x01")                 # scan, while it still tries "Gone"
    run(a, 5)
    assert b"Home2" in ble.values[a.ble.h_wifi]
    ble.phone_writes(a.ble.h_wifi, b"\x02\x05Home2\x06secret")
    run(a, 5)
    assert a.net.wifi_ok and a.net.ssid == "Home2"
    assert json.load(open("settings.json"))["wifi"]["ssid"] == "Home2"


def test_check_for_update_offline_doesnt_restart(board, firmware, run):
    a = firmware("app").App()
    a.updater.check()
    run(a, 5)            # a restart would raise fakes.Reset
    assert a.updater.status()["state"] == "failed"
    assert "no internet" in a.updater.status()["error"]


def test_mqtt_off_without_broker(board, firmware, config, run):
    board.networks = {"Home": "pw"}
    config({"wifi": {"ssid": "Home", "password": "pw"}})
    a = firmware("app").App()
    run(a, 30)
    assert a.net.wifi_ok and not a.net.mqtt_ok


def test_reset_is_visible_to_tests(board, firmware):
    import machine
    with pytest.raises(fakes.Reset):
        machine.reset()
