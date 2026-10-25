"""Drives the real test board for tests/hardware/: its USB serial log and
REPL, files on its flash, and Bluetooth from this PC (bleak, bluetoothctl).

Everything the tests change on the board (config.json, settings.json, paired
phones, the firmware version) is backed up first and put back afterwards.
"""

import asyncio
import ast
import re
import subprocess
import threading
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[2]
UUID = "a7e400%02x-5c2b-4f1a-9d3e-6b8c0f2e1d47"
KEPT_FILES = ("config.json", "settings.json", "ble_bonds.json")


class Board:
    def __init__(self, port):
        self.port = port
        self.lines = []            # (monotonic time, text) of everything the board printed
        self._serial = None
        self._reader = None
        self.open()

    # --- serial log ---------------------------------------------------------------

    def open(self):
        self._serial = serial.Serial(self.port, 115200, timeout=0.2)
        self._stop = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def close(self):
        """Frees the port (for mpremote / tools/deploy.sh)."""
        self._stop = True
        self._reader.join()
        self._serial.close()

    def _read(self):
        """Reads the log; when the USB adapter drops off (it does at some
        restarts, when the radio starts), it reopens the port once it's back.
        Use the /dev/serial/by-id/... name: it stays the same, ttyUSBn may not."""
        buf = b""
        while not self._stop:
            try:
                buf += self._serial.read(512)
            except (serial.SerialException, OSError):
                self.lines.append((time.monotonic(), "[USB adapter dropped off; reopening]"))
                self._reopen()
                continue
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.lines.append((time.monotonic(), line.decode(errors="replace").rstrip("\r")))

    def _reopen(self):
        try:
            self._serial.close()
        except Exception:
            pass
        end = time.monotonic() + 30
        while not self._stop and time.monotonic() < end:
            try:
                port = serial.Serial()
                port.port, port.baudrate, port.timeout = self.port, 115200, 0.2
                port.dtr = port.rts = False          # don't reset the board again on opening
                port.open()
                self._serial = port
                return
            except (serial.SerialException, OSError):
                time.sleep(0.5)

    def mark(self):
        """A point in the log: later waits and greps only look after it."""
        return len(self.lines)

    def log(self, since=0):
        return [text for _, text in self.lines[since:]]

    def wait_for(self, pattern, timeout, since=None):
        """The first log line after `since` matching the regex; AssertionError on timeout."""
        since = self.mark() if since is None else since
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for text in self.log(since):
                m = re.search(pattern, text)
                if m:
                    return m
            time.sleep(0.1)
        raise AssertionError("no %r in the board's log within %d s; last lines:\n%s"
                             % (pattern, timeout, "\n".join(self.log(since)[-15:])))

    def assert_no(self, pattern, since):
        bad = [t for t in self.log(since) if re.search(pattern, t)]
        assert not bad, "unexpected in the board's log: %s" % bad

    # --- REPL -----------------------------------------------------------------------

    def interrupt(self):
        """Stops the app (Ctrl+C) and waits for the REPL prompt. The prompt has
        no newline, so Enter is sent too: it then shows up as a whole line."""
        for _ in range(20):
            mark = self.mark()
            self._serial.write(b"\x03\x03\r")
            time.sleep(0.5)
            if any(t.strip().startswith(">>>") for t in self.log(mark)):
                return
        raise AssertionError("the board doesn't stop for the REPL")

    def exec(self, code, timeout=30):
        """Runs code at the REPL (the app must be stopped) and returns what it
        printed between markers."""
        mark = self.mark()
        body = "print('<<<BEGIN')\n%s\nprint('END>>>')\n" % code
        self._serial.write(b"\x05" + body.encode() + b"\x04")   # paste mode
        self.wait_for(r"^END>>>$", timeout, since=mark)
        out = self.log(mark)
        start = max(i for i, t in enumerate(out) if t == "<<<BEGIN")
        end = max(i for i, t in enumerate(out) if t == "END>>>")
        return out[start + 1:end]

    def fresh_repl(self):
        """A soft reset in raw-REPL mode: MicroPython starts over without
        main.py, so the heap is clean (the stopped app's modules fill it). The
        hardware watchdog isn't fed then: the board restarts within 60 s, so
        use it only for something short, then restart_app()."""
        self.interrupt()
        self._serial.write(b"\x01")
        time.sleep(0.3)
        self._serial.write(b"\x04")
        time.sleep(1.0)
        self._serial.write(b"\x02")
        time.sleep(0.5)
        self.interrupt()

    def eval(self, expression, timeout=30):
        return ast.literal_eval(self.exec("print(repr(%s))" % expression, timeout)[-1])

    def reset(self):
        """Restart (machine.reset() at the REPL); returns the log mark from just before it."""
        self.interrupt()
        mark = self.mark()
        self._serial.write(b"\x05import machine; machine.reset()\n\x04")
        return mark

    def restart_app(self, timeout=60):
        mark = self.reset()
        self.wait_for(r"^Running$", timeout, since=mark)
        return mark

    # --- files ------------------------------------------------------------------------

    def read_file(self, name):
        """Contents (bytes), or None if missing. The app must be stopped."""
        return self.eval("open(%r,'rb').read() if %r in __import__('os').listdir() else None" % (name, name))

    def write_file(self, name, data, chunk=256):
        """In pieces: a big literal pasted at the REPL can exhaust its memory."""
        data = bytes(data)
        self.exec("f = open(%r, 'wb')\nf.close()" % name)
        for i in range(0, len(data), chunk):
            self.exec("f = open(%r, 'ab')\nf.write(%r)\nf.close()" % (name, data[i:i + chunk]))

    def remove_file(self, name):
        self.exec("import os\ntry:\n    os.remove(%r)\nexcept OSError:\n    pass" % name)

    def backup(self):
        self.interrupt()
        return {name: self.read_file(name) for name in KEPT_FILES}

    def restore(self, saved):
        self.interrupt()
        for name, data in saved.items():
            if data is None:
                self.remove_file(name)
            else:
                self.write_file(name, data)

    def deploy(self):
        """tools/deploy.sh: the firmware in this checkout, config.json untouched."""
        self.close()
        try:
            subprocess.run([str(ROOT / "tools" / "deploy.sh")], check=True, cwd=ROOT,
                           env={**__import__("os").environ, "PORT": self.port},
                           stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=300)
        finally:
            self.open()


# --- Bluetooth from this PC ---------------------------------------------------------------


def _run(coro, timeout=60):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def find(name_prefix="Air-Monitor", timeout=20):
    """(address, name) of the first board advertising with that name."""
    from bleak import BleakScanner

    async def scan():
        devices = await BleakScanner.discover(timeout=timeout, service_uuids=[UUID % 0])
        for d in devices:
            if (d.name or "").startswith(name_prefix):
                return d.address, d.name
        return None
    return _run(scan(), timeout + 10)


def read(address, short):
    from bleak import BleakClient

    async def go():
        async with BleakClient(address, timeout=20) as client:
            return bytes(await client.read_gatt_char(UUID % short))
    return _run(go())


def write(address, short, value):
    """Raises (bleak.exc.BleakError) when the board refuses the write."""
    from bleak import BleakClient

    async def go():
        async with BleakClient(address, timeout=20) as client:
            await client.write_gatt_char(UUID % short, bytes(value), response=True)
    _run(go())


def forget(address):
    """Removes this PC's pairing with the board (BlueZ)."""
    subprocess.run(["bluetoothctl", "remove", address], capture_output=True, timeout=20)


def pair(address, timeout=60, attempts=3):
    """Pairs and bonds this PC with the board (Just Works, no code). The
    board's pairing window must be open. BlueZ's discovery is flaky (it drops
    devices from its list mid-scan, "DEL Device ..."): scan, pair as soon as
    the board is seen, and try again a few times."""
    import pexpect
    forget(address)   # a refused pairing can leave BlueZ's half behind ("already exists")
    ctl = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=timeout)
    try:
        ctl.sendline("agent NoInputNoOutput")
        ctl.sendline("default-agent")
        for attempt in range(attempts):
            ctl.sendline("scan on")
            ctl.expect(address, timeout=30)
            ctl.sendline("pair %s" % address)
            if ctl.expect([r"Pairing successful", r"Failed to pair", pexpect.TIMEOUT], timeout=25) == 0:
                ctl.sendline("scan off")
                return
            ctl.sendline("scan off")
            ctl.sendline("remove %s" % address)
            time.sleep(2)
        raise AssertionError("pairing with %s failed %d times" % (address, attempts))
    finally:
        ctl.sendline("quit")
        ctl.close()
