"""A board that can't get on a network must not hammer the access point (a
board at work with a wrong password re-joined every ~12 s for hours and
filled the router's client table). Retries back off from 30 s to 30 min; a
refused password waits at least 10 min; the driver's own retries are capped."""

import sys

import pytest


def station():
    return sys.modules["network"].WLAN(0)


@pytest.fixture
def wrong_password(board, firmware, config):
    board.networks = {"Work": "right"}
    config({"wifi": {"ssid": "Work", "password": "wrong"}, "display": {"enabled": False}})
    return firmware("app").App()


def test_driver_retries_are_capped(board, wrong_password):
    assert station().settings.get("reconnects") == 2


def test_wrong_password_is_tried_rarely(board, wrong_password, run):
    run(wrong_password, 3600, step_ms=5000)          # an hour
    assert station().attempts <= 8                   # was ~120 (every 30 s), the router saw one every ~12 s
    assert wrong_password.net.wifi_state() in ((3, 1), (0, 0))


def test_missing_network_backs_off_to_30_minutes(board, firmware, config, run):
    config({"wifi": {"ssid": "Gone", "password": "pw"}, "display": {"enabled": False}})
    a = firmware("app").App()
    run(a, 3600, step_ms=5000)
    # 30 s, 1, 2, 4, 8, 16, 30 min ...: about 8 tries in the first hour
    assert 5 <= station().attempts <= 10
    before = station().attempts
    run(a, 3600, step_ms=5000)                       # then at most every 30 min
    assert station().attempts - before <= 3


def test_network_back_connects_and_the_backoff_starts_over(board, firmware, config, run):
    config({"wifi": {"ssid": "Home", "password": "pw"}, "display": {"enabled": False}})
    a = firmware("app").App()
    run(a, 1800, step_ms=5000)                       # backed off to many minutes
    board.networks = {"Home": "pw"}                  # the router is back
    run(a, 1900, step_ms=5000)                       # at most one long wait later
    assert a.net.wifi_ok
    station().disconnect()                           # dropped once more
    run(a, 40, step_ms=1000)
    assert a.net.wifi_ok                             # back within ~30 s, not 30 min


def test_choosing_a_network_in_the_app_tries_at_once(board, wrong_password, run):
    run(wrong_password, 1200, step_ms=5000)          # long backoff by now
    board.networks["Home"] = "pw"
    wrong_password.net.set_wifi("Home", "pw")
    run(wrong_password, 2)
    assert wrong_password.net.wifi_ok
