"""Every test gets a fresh fake board (tests/fakes.py) in an empty folder that
plays the board's flash, with the firmware imported as on an ESP32."""

import json
import shutil
import sys

import pytest

import fakes

FIRMWARE_MODULES = ("app", "net", "sensors", "ui", "ui_more", "gfx", "assets", "commands", "home_assistant", "ble",
                    "selfcal", "clock", "weather", "updater", "version", "signature", "release_key")


@pytest.fixture
def board(tmp_path, monkeypatch):
    """The fake board; the current directory is its flash."""
    b = fakes.install()
    b.__init__()
    monkeypatch.chdir(tmp_path)
    shutil.copy(fakes.ROOT / "firmware" / "assets.bin", tmp_path)   # fonts and icons live in flash
    for name in FIRMWARE_MODULES:
        sys.modules.pop(name, None)
    sys.modules["umqtt.simple"].MQTTClient.broker_up = False
    sys.modules["umqtt.simple"].MQTTClient.inbox = []
    sys.modules["network"] = fakes._network()
    return b


@pytest.fixture
def firmware(board, monkeypatch):
    """Imports a firmware module as the ESP32 would see it: firmware("app")."""
    def load(name):
        real, sys.platform = sys.platform, "esp32"
        try:
            updater = __import__("updater")   # first: App imports it later, inside App()
            module = __import__(name)
        finally:
            sys.platform = real
        if not getattr(updater, "_in_fake_flash", False):
            # Its files are absolute ("/update_check"): on the PC, keep them in the fake flash.
            for attr in ("UPDATE_DIR", "PENDING", "CHECK_FLAG", "INSTALL_FLAG", "STATUS_FILE", "BAD_FILE", "SOURCE_FILE"):
                setattr(updater, attr, getattr(updater, attr).lstrip("/"))
            updater._in_fake_flash = True
        return module
    return load


@pytest.fixture
def config(board):
    """Writes config.json on the fake flash: config({...})."""
    def write(cfg):
        with open("config.json", "w") as f:
            json.dump(cfg, f)
    return write


class _Stop(Exception):
    pass


@pytest.fixture
def run(board, monkeypatch):
    """run(app, seconds): the real main loop, for that long in fake time."""
    import time

    def run_for(app, seconds, step_ms=200):
        """Each pass of the loop advances fake time by at least step_ms (the
        board sleeps 20 ms per pass; finer steps only make tests slower)."""
        end = board.ms + int(seconds * 1000)

        def sleep_ms(ms):
            board.ms += max(ms, step_ms)
            if board.ms >= end:
                raise _Stop()
        monkeypatch.setattr(time, "sleep_ms", sleep_ms)
        try:
            app.loop()
        except _Stop:
            pass
    return run_for
