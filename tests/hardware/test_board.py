"""The real board: start-up, Bluetooth pairing and protected writes, running
without its network, and signed over-the-air updates.

The tests run in this order and share the board (see conftest.py). They take
about 10 minutes, mostly waiting for restarts and the update downloads.
"""

import functools
import http.server
import json
import os
import random
import shutil
import socket
import subprocess
import threading
import time

import pytest

import board as hw

COMMAND, IDENTIFY, FACTORY_RESET, OPEN_PAIRING = 0x07, b"\x04", b"\x02", b"\x06"
ENV, AIR = 0x01, 0x0A


# --- start-up ----------------------------------------------------------------------------


def test_boots_and_finds_its_sensors(dut):
    mark = dut.restart_app()
    dut.wait_for(r"AHT21 found", 1, since=mark)
    dut.wait_for(r"ENS160 found", 1, since=mark)
    dut.wait_for(r"Bluetooth: advertising as ", 1, since=mark)
    time.sleep(20)
    dut.assert_no(r"Traceback|Error|Watchdog", since=mark)


# --- Bluetooth ---------------------------------------------------------------------------------


def test_readings_are_public(dut, address):
    assert len(hw.read(address, ENV)) == 27
    assert len(hw.read(address, AIR)) >= 10


def _close_pairing_window(dut):
    """Restart, then wait out the first 2 minutes (once a phone is bonded)."""
    mark = dut.restart_app()
    dut.wait_for(r"pairing window open for 120 s \(after start-up\)", 1, since=mark)
    dut.wait_for(r"pairing window closed", 130, since=mark)
    return mark


def test_first_setup_opens_the_pairing_window(dut):
    dut.interrupt()
    dut.remove_file("ble_bonds.json")         # no phone bonded (restored at the end)
    mark = dut.restart_app()
    dut.wait_for(r"pairing window open for 600 s \(no phone paired yet\)", 1, since=mark)


def test_pairing_without_code_in_the_window_allows_writes(dut, address):
    hw.pair(address)
    mark = dut.mark()
    hw.write(address, COMMAND, IDENTIFY)
    dut.wait_for(r"Bluetooth: command 4", 10, since=mark)
    dut.wait_for(r"new phone paired, link encrypted", 1, since=0)


def test_bonded_phone_connects_any_time(dut, address):
    _close_pairing_window(dut)                # window closed: bonded phones still connect
    mark = dut.mark()
    hw.write(address, COMMAND, IDENTIFY)
    dut.wait_for(r"paired phone, link encrypted", 15, since=mark)
    dut.wait_for(r"Bluetooth: command 4", 10, since=mark)
    dut.assert_no(r"not paired", since=mark)


def test_unpaired_phone_is_dropped_outside_the_window(dut, address):
    hw.forget(address)                        # (window still closed) the PC forgets its bond: a stranger
    mark = dut.mark()
    with pytest.raises(Exception):
        hw.write(address, COMMAND, IDENTIFY)
    dut.wait_for(r"phone not paired, disconnected", 15, since=mark)
    dut.assert_no(r"Bluetooth: command 4", since=mark)


def test_re_pairing_outside_the_window_is_refused(dut, address):
    """Like someone copying a bonded phone's address: NimBLE deletes the old
    bond first. The board must keep its bonds, refuse, and keep running (an
    earlier version made NimBLE loop forever here)."""
    dut.interrupt()
    before = dut.read_file("ble_bonds.json")
    _close_pairing_window(dut)
    mark = dut.mark()
    with pytest.raises(Exception):
        hw.pair(address, timeout=30)
        hw.write(address, COMMAND, IDENTIFY)
    dut.wait_for(r"phone not paired, disconnected", 20, since=mark)
    dut.assert_no(r"Bluetooth: command 4", since=mark)
    dut.interrupt()                           # still answers
    assert dut.read_file("ble_bonds.json") == before


def test_restart_opens_the_window_again(dut, address):
    mark = dut.restart_app()
    dut.wait_for(r"pairing window open for 120 s \(after start-up\)", 1, since=mark)
    hw.pair(address)                          # the PC pairs again (it forgot its bond above)
    mark = dut.mark()
    hw.write(address, COMMAND, IDENTIFY)
    dut.wait_for(r"Bluetooth: command 4", 10, since=mark)


def test_bonded_phone_can_open_the_window(dut, address):
    mark = dut.mark()
    hw.write(address, COMMAND, OPEN_PAIRING)
    dut.wait_for(r"pairing window open for 120 s \(asked by a paired phone\)", 10, since=mark)


def test_factory_reset_forgets_paired_phones(dut, address):
    mark = dut.mark()
    hw.write(address, COMMAND, FACTORY_RESET)
    dut.wait_for(r"^Running$", 60, since=mark)
    dut.wait_for(r"pairing window open for 600 s \(no phone paired yet\)", 1, since=mark)
    hw.forget(address)              # this PC forgets too, else it would try the old keys


# --- without its network --------------------------------------------------------------------


def test_runs_without_its_network(dut, address, config_json):
    cfg = dict(config_json, wifi={"ssid": "aqs-test-missing-%d" % random.randrange(10 ** 6), "password": "x"})
    dut.write_file("config.json", json.dumps(cfg).encode())
    dut.remove_file("settings.json")          # a network chosen in the app would win
    mark = dut.restart_app()
    time.sleep(90)                            # the old firmware restarted after ~40 s
    dut.assert_no(r"Traceback|Watchdog|restarting|rst:", since=mark)
    assert hw.find(timeout=15), "not reachable over Bluetooth without Wi-Fi"
    dut.interrupt()
    dut.write_file("config.json", json.dumps(config_json).encode())
    dut.restart_app()


# --- signed updates ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    """Test releases built from this checkout in a copy: 99.0.0 signed with the
    release key, 99.0.1 without signature, 99.0.2 with a forged one."""
    work = tmp_path_factory.mktemp("releases")
    copy = work / "repo"
    shutil.copytree(hw.ROOT, copy, ignore=shutil.ignore_patterns(".git", ".venv", "dist", "build", "android",
                                                                 "__pycache__", ".pytest_cache"))
    (copy / ".venv").symlink_to(hw.ROOT / ".venv")
    changelog = copy / "CHANGELOG.md"
    for version in ("99.0.0", "99.0.1", "99.0.2"):
        changelog.write_text("## %s\n\nHardware test release.\n\n" % version + changelog.read_text())
        subprocess.run([str(copy / ".venv" / "bin" / "python"), "tools/release.py", version], cwd=copy, check=True,
                       capture_output=True)
    dist = copy / "dist"
    (dist / "v99.0.1" / "manifest.sig").unlink()
    (dist / "v99.0.2" / "manifest.sig").write_bytes(os.urandom(384))
    return dist


@pytest.fixture(scope="module")
def server(releases):
    """Serves the test releases on this PC's LAN address."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(releases))
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect(("192.0.2.1", 9))           # no packet sent: just picks the LAN interface
    ip = probe.getsockname()[0]
    probe.close()
    yield "http://%s:%d/" % (ip, httpd.server_address[1])
    httpd.shutdown()


def _update(dut, base, flag):
    dut.interrupt()
    dut.write_file("update_source", base.encode())
    dut.write_file(flag, b"1")
    return dut.reset()


def test_signature_check_on_the_device(dut, releases):
    dut.interrupt()
    data = (releases / "v99.0.0" / "manifest.json").read_bytes()
    sig = (releases / "v99.0.0" / "manifest.sig").read_bytes()
    out = dut.exec("import time, updater\nt = time.ticks_ms()\nm = updater.check_manifest(%r, %r)\n"
                   "print(m['version'], time.ticks_diff(time.ticks_ms(), t))\n"
                   "try:\n    updater.check_manifest(%r, %r)\n    print('forged accepted')\n"
                   "except OSError as e:\n    print('forged refused:', e)" % (data, sig, data.replace(b"99.0.0", b"99.0.9"), sig))
    version, ms = out[-2].split()
    assert version == "99.0.0" and int(ms) < 2000, out
    assert out[-1].startswith("forged refused: signature invalid"), out
    dut.restart_app()


@pytest.mark.parametrize("version,error", [("99.0.1", "404"), ("99.0.2", "signature invalid")])
def test_unsigned_or_forged_release_is_refused(dut, online, server, version, error):
    mark = _update(dut, server + "v%s/" % version, "update_install")
    dut.wait_for(r"Update: check failed: .*%s" % error, 90, since=mark)
    dut.wait_for(r"^Running$", 60, since=mark)
    dut.assert_no(r"Update installed", since=mark)


def test_signed_release_installs_and_is_confirmed(dut, online, server):
    mark = _update(dut, server + "v99.0.0/", "update_install")
    dut.wait_for(r"Update: 99.0.0 downloaded, restarting to install", 240, since=mark)
    dut.wait_for(r"Update installed: 99.0.0", 60, since=mark)
    dut.wait_for(r"Update confirmed: 99.0.0", 150, since=mark)
    dut.interrupt()
    dut.remove_file("update_source")          # back to GitHub; the session end redeploys this checkout
