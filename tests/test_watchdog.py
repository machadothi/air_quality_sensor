"""The hardware watchdog (ESP32): fed every 5 s by the watchdog timer while the
main loop runs; a loop stuck in Python is restarted after 2 minutes; at the
REPL (Ctrl+C) it keeps being fed. A hang in C stops the timer callback too,
and the hardware watchdog restarts the board (that part needs the real chip:
tests/hardware)."""

import pytest

import fakes


@pytest.fixture
def app(firmware):
    return firmware("app").App()


def test_started_with_a_minute_and_fed_while_running(board, app, run):
    run(app, 10)
    assert board.wdt_timeout == 60000
    app._watchdog(None)
    assert board.wdt_feeds == 1


def test_stuck_loop_restarts(board, app, run):
    run(app, 1)
    board.ms += 121 * 1000                   # the loop hasn't run for 2 minutes
    with pytest.raises(fakes.Reset):
        app._watchdog(None)


def test_stopped_at_the_repl_keeps_feeding(board, app, run):
    run(app, 1)
    app.stopped = True                       # Ctrl+C
    board.ms += 10 * 60 * 1000
    app._watchdog(None)                      # no restart
    assert board.wdt_feeds == 1


def test_ctrl_c_marks_it_stopped(board, app, monkeypatch):
    import time

    def interrupt(ms):
        raise KeyboardInterrupt
    monkeypatch.setattr(time, "sleep_ms", interrupt)
    with pytest.raises(KeyboardInterrupt):
        app.loop()
    assert app.stopped
