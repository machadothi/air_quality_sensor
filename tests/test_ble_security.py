"""Bluetooth: readings are public, every write and the Wi-Fi details need a
paired phone; pairing shows a passkey on the display (security review)."""

import json
import random

import pytest

WRITE, READ = 0x0008, 0x0002
READ_ENC, READ_AUTH, WRITE_ENC, WRITE_AUTH = 0x0200, 0x0400, 0x1000, 0x2000
WRITABLE = (0x07, 0x08, 0x09, 0x0C, 0x0D, 0x0E, 0x0F, 0x10)
PUBLIC_READINGS = (0x01, 0x06, 0x0A, 0x0B)


@pytest.fixture
def app(firmware):
    return firmware("app").App()


def test_every_write_needs_a_passkey_paired_phone(board, app):
    for uuid in WRITABLE:
        flags = board.ble.flags(uuid)
        assert flags & WRITE and flags & WRITE_AUTH, hex(uuid)
    assert board.ble.flags(0x0E) & READ_AUTH          # Wi-Fi details
    for uuid in PUBLIC_READINGS:
        assert not board.ble.flags(uuid) & (READ_ENC | READ_AUTH | WRITE)
    assert board.ble.settings["mitm"] and board.ble.settings["bond"] and board.ble.settings["le_secure"]
    assert board.ble.settings["io"] == 0              # display only: the board shows the passkey


def test_without_display_writes_still_need_encryption(board, firmware, config):
    config({"display": {"enabled": False}})
    firmware("app").App()
    for uuid in WRITABLE:
        assert board.ble.flags(uuid) & WRITE_ENC and not board.ble.flags(uuid) & WRITE_AUTH
    assert not board.ble.settings["mitm"] and board.ble.settings["io"] == 3


def test_fixed_passkey_without_display(board, firmware, config):
    config({"display": {"enabled": False}, "bluetooth": {"passkey": "246810"}})
    a = firmware("app").App()
    assert board.ble.flags(0x0E) & WRITE_AUTH
    board.ble.irq_handler(31, (0, 3, 0))              # the phone starts pairing
    assert board.ble.passkeys == [(0, 3, 246810)]
    assert a.ble.pairing_code == 246810


def test_pairing_code_is_shown_and_cleared(board, app):
    board.ble.irq_handler(1, (0, 0, b"\0" * 6))       # connect
    board.ble.irq_handler(31, (0, 3, 0))              # passkey action: display
    (conn, action, code), = board.ble.passkeys
    assert 0 <= code <= 999999
    app.ble.poll()
    assert app.display.notice[0] == "%03d %03d" % (code // 1000, code % 1000)
    board.ble.irq_handler(28, (0, True, True, True, 16))   # encrypted, authenticated, bonded
    app.ble.poll()
    assert app.display.notice is None


def test_pairing_codes_differ(board, app):
    codes = set()
    for _ in range(20):
        board.ble.irq_handler(31, (0, 3, 0))
        codes.add(board.ble.passkeys[-1][2])
    assert len(codes) > 15


def test_paired_phones_are_remembered_and_forgotten_on_factory_reset(board, firmware, app):
    assert board.ble.irq_handler(30, (1, b"\x01\x02", b"secret-key")) is True
    app.ble.poll()                                    # written to flash outside the callback
    assert json.load(open("ble_bonds.json"))
    firmware("ble").Ble(app)                          # after a restart
    assert board.ble.irq_handler(29, (1, 0, None)) == b"secret-key"
    assert board.ble.irq_handler(29, (1, 0, b"\x01\x02")) == b"secret-key"
    app.factory_reset()
    with pytest.raises(OSError):
        open("ble_bonds.json")


def test_bond_store_is_bounded(board, app):
    results = [board.ble.irq_handler(30, (1, bytes([i, i]), b"v")) for i in range(100)]
    assert results.count(True) == 48


def test_write_queue_is_bounded(board, app):
    for _ in range(50):
        board.ble.phone_writes(app.ble.h_command, b"\x04")
    assert len(app.ble.pending) == 8


def test_too_long_wifi_name_is_ignored(board, app):
    app.ble._handle_write(app.ble.h_wifi, b"\x02\x28" + b"x" * 40 + b"\x02pw")
    assert app.net.ssid == ""


def test_random_writes_never_stop_the_board(board, app, run):
    rng = random.Random(1)
    handles = [app.ble.h_command, app.ble.h_name, app.ble.h_display, app.ble.h_calibration, app.ble.h_time,
               app.ble.h_wifi, app.ble.h_weather, app.ble.h_update]
    for _ in range(300):
        value = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        if value[:1] in (b"\x02", b"\x03") and rng.random() < 0.9:
            value = b"\x04" + value[1:]               # mostly avoid factory reset / reboot ending the run
        board.ble.phone_writes(rng.choice(handles), value)
        try:
            app.ble.poll()
        except Exception as e:                        # only a requested restart may stop it
            pytest.fail("a write stopped the board: %r" % e)
        app.reboot_at = None
        app.updater._restart_at = None
