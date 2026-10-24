"""Bluetooth: readings are public (BTHome, for Home Assistant); only bonded
phones stay connected, and only they can write. Pairing needs no code but is
only possible while the pairing window is open (security review, pairing
window)."""

import json
import random

import pytest

WRITE, READ = 0x0008, 0x0002
READ_ENC, WRITE_ENC = 0x0200, 0x1000
WRITABLE = (0x07, 0x08, 0x09, 0x0C, 0x0D, 0x0E, 0x0F, 0x10)
PUBLIC_READINGS = (0x01, 0x06, 0x0A, 0x0B)
IDENTIFY, OPEN_PAIRING = b"\x04", b"\x06"


def bonded_before(phone=b"phone-1"):
    """ble_bonds.json as if that phone had paired earlier."""
    json.dump({"2:" + phone.hex(): "aa", "1:" + phone.hex(): "bb"}, open("ble_bonds.json", "w"))


@pytest.fixture
def app(firmware):
    return firmware("app").App()


@pytest.fixture
def bonded_app(board, firmware):
    bonded_before()
    return firmware("app").App()


def test_flags_writes_need_an_encrypted_bonded_link(board, app):
    for uuid in WRITABLE:
        assert board.ble.flags(uuid) & WRITE and board.ble.flags(uuid) & WRITE_ENC, hex(uuid)
    assert board.ble.flags(0x0E) & READ_ENC          # Wi-Fi details
    for uuid in PUBLIC_READINGS:
        assert not board.ble.flags(uuid) & (READ_ENC | WRITE)
    s = board.ble.settings
    assert s["bond"] and s["le_secure"] and not s["mitm"] and s["io"] == 3   # Just Works: no code


def test_first_setup_window_while_no_phone_is_bonded(board, app):
    assert app.ble.pairing_open()
    board.ms += 601 * 1000
    assert not app.ble.pairing_open()


def test_window_closed_once_a_phone_is_bonded(board, bonded_app):
    assert not bonded_app.ble.pairing_open()
    assert bonded_app.ble._app_packet()[-1] == 0                    # advertised: closed


def test_double_reset_opens_the_window(board, firmware, monkeypatch):
    bonded_before()
    ble = firmware("ble")
    monkeypatch.setattr(ble, "_reset_presses", lambda: 2)
    a = firmware("app").App()
    assert a.ble.pairing_open() and a.ble._app_packet()[-1] == 1   # advertised: open
    board.ms += 121 * 1000
    assert not a.ble.pairing_open()


def test_single_reset_doesnt(board, firmware, monkeypatch):
    bonded_before()
    monkeypatch.setattr(firmware("ble"), "_reset_presses", lambda: 1)
    assert not firmware("app").App().ble.pairing_open()


def test_stranger_is_dropped_outside_the_window(board, bonded_app, run):
    board.ble.phone_connects()                       # no bond: can't encrypt
    run(bonded_app, 3)
    assert board.ble.security_requests == [0] and not board.ble.disconnects   # asked after 1.5 s, waiting
    run(bonded_app, 6)
    assert board.ble.disconnects == [0] and bonded_app.ble.connection is None


def test_stranger_cant_pair_outside_the_window(board, bonded_app, run):
    board.ble.phone_connects(pair_as=b"stranger")
    run(bonded_app, 1)
    assert board.ble.disconnects == [0]
    assert not any("stranger".encode().hex() in k for k in json.load(open("ble_bonds.json")))


def test_new_keys_for_a_known_address_need_the_window(board, bonded_app, run):
    board.ble.phone_connects(pair_as=b"phone-1")      # the bonded phone's address, other keys
    run(bonded_app, 1)
    assert board.ble.disconnects == [0]
    assert json.load(open("ble_bonds.json"))["2:" + b"phone-1".hex()] == "aa"   # unchanged


def test_new_pairing_outside_the_window_isnt_trusted_even_briefly(board, bonded_app, run):
    board.ble.phone_connects(pair_as=b"stranger")    # encrypted first, keys after (as NimBLE does)
    board.ble.phone_writes(bonded_app.ble.h_wifi, b"\x02\x04Evil\x02pw")
    run(bonded_app, 3)
    assert not bonded_app.ble.trusted and board.ble.disconnects == [0]
    assert bonded_app.net.ssid != "Evil"


def test_bonds_cant_be_deleted_outside_the_window(board, bonded_app, run):
    board.ble.phone_connects()
    assert board.ble.irq_handler(30, (2, b"phone-1", None)) is True    # NimBLE's delete before re-pairing: "done"
    assert board.ble.irq_handler(30, (2, b"phone-1", None)) is False   # ... and "not found" after that (NimBLE loops)
    assert board.ble.irq_handler(29, (2, 0, b"phone-1")) is None       # hidden from NimBLE meanwhile
    board.ble.irq_handler(28, (0, True, False, True, 16))             # the re-pairing: encrypted, then new keys
    assert board.ble.irq_handler(30, (2, b"phone-1", b"new")) is False
    run(bonded_app, 1)
    assert board.ble.disconnects == [0] and bonded_app.ble.bonded_phones() == 1
    assert board.ble.irq_handler(29, (2, 0, b"phone-1")) == b"\xaa"   # back after the disconnect


def test_failed_try_in_the_window_may_be_followed_by_pairing(board, firmware, monkeypatch, run):
    bonded_before()
    monkeypatch.setattr(firmware("ble"), "_reset_presses", lambda: 2)
    a = firmware("app").App()
    board.ble.phone_connects()
    board.ble.irq_handler(28, (0, False, False, False, 0))          # its stale keys didn't work
    run(a, 3)
    assert not board.ble.disconnects
    board.ble.irq_handler(28, (0, True, False, True, 16))           # then it pairs anew
    board.ble.irq_handler(30, (2, b"phone-1", b"new-keys"))
    run(a, 3)
    assert a.ble.trusted


def test_bonded_phone_stays_and_can_write(board, bonded_app, run):
    board.ble.phone_connects(bond="known")
    run(bonded_app, 30)
    assert not board.ble.disconnects and bonded_app.ble.trusted
    mark = bonded_app.ble.identify_until
    board.ble.phone_writes(bonded_app.ble.h_command, IDENTIFY)
    run(bonded_app, 1)
    assert bonded_app.ble.identify_until != mark


def test_new_phone_pairs_in_the_window(board, firmware, monkeypatch, run):
    bonded_before()
    monkeypatch.setattr(firmware("ble"), "_reset_presses", lambda: 2)
    a = firmware("app").App()
    board.ble.phone_connects(pair_as=b"phone-2")
    run(a, 10)
    assert a.ble.trusted and not board.ble.disconnects and a.ble.bonded_phones() == 2


def test_writes_before_the_bond_is_proven_are_ignored(board, bonded_app, run):
    board.ble.phone_connects()
    board.ble.phone_writes(bonded_app.ble.h_wifi, b"\x02\x04Evil\x02pw")
    run(bonded_app, 1)
    assert bonded_app.net.ssid != "Evil"


def test_bonded_phone_can_open_the_window_for_another(board, bonded_app, run):
    board.ble.phone_connects(bond="known")
    board.ble.phone_writes(bonded_app.ble.h_command, OPEN_PAIRING)   # held until the bond is checked
    run(bonded_app, 3)
    assert bonded_app.ble.pairing_open()


def test_display_shows_the_open_window(board, firmware, monkeypatch, run):
    bonded_before()
    monkeypatch.setattr(firmware("ble"), "_reset_presses", lambda: 2)
    a = firmware("app").App()
    run(a, 2)
    assert a.display.notice[0] == "Pairing open" and "left" in a.display.notice[1]
    run(a, 120)
    assert a.display.notice is None


def test_paired_phones_are_remembered_and_forgotten_on_factory_reset(board, firmware, app, run):
    board.ble.phone_connects(pair_as=b"phone-1")     # first-setup window
    run(app, 1)
    assert json.load(open("ble_bonds.json"))
    again = firmware("ble").Ble(app)                 # after a restart
    assert again.bonded_phones() == 1 and not again.pairing_open()
    assert board.ble.irq_handler(29, (2, 0, None)) == b"peer-keys"
    app.factory_reset()
    with pytest.raises(OSError):
        open("ble_bonds.json")


def test_bond_store_is_bounded(board, app):
    results = [board.ble.irq_handler(30, (3, bytes([i, i]), b"v")) for i in range(100)]
    assert results.count(True) == 48


def test_write_queue_is_bounded(board, app):
    for _ in range(50):
        board.ble.phone_writes(app.ble.h_command, IDENTIFY)
    assert len(app.ble.pending) == 8


def test_too_long_wifi_name_is_ignored(board, app):
    board.ble.phone_connects(pair_as=b"phone")
    app.ble._handle_write(app.ble.h_wifi, b"\x02\x28" + b"x" * 40 + b"\x02pw")
    assert app.net.ssid == ""


def test_random_writes_never_stop_the_board(board, app):
    board.ble.phone_connects(pair_as=b"phone")
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
