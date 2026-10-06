# Over-the-air updates (ESP32) from GitHub releases.
#
# GitHub needs HTTPS, and with Bluetooth, MQTT and the display running the ESP32
# has too little RAM left for a TLS connection. So checking and downloading
# happen in a short *maintenance start* instead: a request (from the app, MQTT,
# or the nightly check) leaves a marker file and restarts the board, and main.py
# calls maintenance() before loading the app, while the RAM is still free:
#
#   /update_check    fetch https://github.com/<repo>/releases/latest/download/manifest.json
#                    {"version", "notes", "mpy": 6, "files": [{"name", "size", "sha256"}]}
#   /update_install  download every file into /update/ (SHA-256 checked), write
#                    /update_pending and restart: boot.py moves the old files to
#                    /previous/ and the new ones into place, and rolls back if the
#                    new version doesn't run healthily within two starts.
#   /update_status.json  the outcome, which the running app shows (Updater below).
#
# An update is installed only after a "yes" in the app (or MQTT /update install),
# unless "update": {"auto": true}. A version that was rolled back (/update_bad)
# is never installed automatically. requests can't follow GitHub's redirects or
# chunked replies, and files go to flash, not RAM: hence the small HTTP client.
import gc
import json
import os
import sys
import time

from micropython import const

from version import VERSION

REPO = "machadothi/air_quality_sensor"
_MANIFEST_URL = "https://github.com/%s/releases/latest/download/manifest.json" % REPO
_FILE_URL = "https://github.com/%s/releases/download/v%s/%s"
UPDATE_DIR = "/update"
PENDING = "/update_pending"
CHECK_FLAG = "/update_check"
INSTALL_FLAG = "/update_install"
STATUS_FILE = "/update_status.json"
BAD_FILE = "/update_bad"         # written by boot.py after a rollback
SOURCE_FILE = "/update_source"   # testing: a base URL instead of GitHub

IDLE = const(0)
CHECKING = const(1)
AVAILABLE = const(2)
DOWNLOADING = const(3)
RESTARTING = const(4)
FAILED = const(5)
UP_TO_DATE = const(6)
STATES = ("idle", "checking", "available", "downloading", "restarting", "failed", "up to date")

_CHECK_HOUR = const(3)   # nightly check at 03:30 local time


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _rmtree(path):
    try:
        for name in os.listdir(path):
            os.remove(path + "/" + name)
        os.rmdir(path)
    except OSError:
        pass


def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def _write_status(state, manifest=None, error=None):
    with open(STATUS_FILE, "w") as f:
        json.dump({"state": state, "manifest": manifest, "error": error}, f)


# --- HTTP(S) -----------------------------------------------------------------------


def _open(url):
    """GET url, following redirects. Returns (socket, headers dict)."""
    import socket
    import ssl
    for _ in range(5):
        proto, _, host, path = url.split("/", 3)
        port = 443 if proto == "https:" else 80
        if ":" in host:
            host, port = host.split(":")[0], int(host.split(":")[1])
        addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        s = socket.socket()
        s.settimeout(15)
        s.connect(addr)
        if proto == "https:":
            s = ssl.wrap_socket(s, server_hostname=host)
        s.write(b"GET /%s HTTP/1.1\r\nHost: %s\r\nUser-Agent: air-monitor\r\nConnection: close\r\n\r\n"
                % (path.encode(), host.encode()))
        status = int(s.readline().split(None, 2)[1])
        hdrs = {}
        while True:
            line = s.readline()
            if not line or line == b"\r\n":
                break
            k, _, v = line.decode().partition(":")
            hdrs[k.strip().lower()] = v.strip()
        if 300 <= status < 400 and "location" in hdrs:
            s.close()
            loc = hdrs["location"]
            url = loc if "://" in loc else "%s//%s%s" % (proto, host, loc)
            continue
        if status != 200:
            s.close()
            raise OSError("HTTP %d" % status)
        return s, hdrs
    raise OSError("too many redirects")


def _body(s, hdrs, sink):
    """Stream the body (plain or chunked) into sink(bytes)."""
    if hdrs.get("transfer-encoding", "").lower() == "chunked":
        while True:
            size = int(s.readline().split(b";")[0], 16)
            if size == 0:
                break
            while size:
                chunk = s.read(min(size, 1024))
                sink(chunk)
                size -= len(chunk)
            s.readline()
    else:
        left = int(hdrs.get("content-length", "-1"))
        while left != 0:
            chunk = s.read(1024 if left < 0 else min(left, 1024))
            if not chunk:
                break
            sink(chunk)
            left -= len(chunk)


def _get_json(url):
    s, hdrs = _open(url)
    data = bytearray()
    try:
        _body(s, hdrs, data.extend)
    finally:
        s.close()
    return json.loads(bytes(data))


def _download(url, path, sha256):
    """One file to flash, its SHA-256 checked."""
    import binascii
    import hashlib
    digest = hashlib.sha256()
    with open(path, "wb") as out:
        def sink(chunk):
            digest.update(chunk)
            out.write(chunk)
        s, hdrs = _open(url)
        try:
            _body(s, hdrs, sink)
        finally:
            s.close()
    if binascii.hexlify(digest.digest()).decode() != sha256:
        raise OSError("checksum mismatch")


# --- maintenance start (main.py, before the app) ---------------------------------------


def _connect_wifi():
    """The network from config.json, or the one chosen in the app (settings.json)."""
    import network
    with open("config.json") as f:
        wifi = json.load(f)["wifi"]
    try:
        with open("settings.json") as f:
            wifi.update(json.load(f).get("wifi") or {})
    except (OSError, ValueError):
        pass
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(wifi["ssid"], wifi["password"])
        start = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > 20000:
                raise OSError("no Wi-Fi")
            time.sleep_ms(200)


def maintenance():
    """Called by main.py before the app: does a requested check or install."""
    install = _exists(INSTALL_FLAG)
    if not (install or _exists(CHECK_FLAG)):
        return
    _remove(CHECK_FLAG)   # first: a crash in here must not repeat at every start
    _remove(INSTALL_FLAG)
    source = _read(SOURCE_FILE) or None
    print("Update: maintenance start (%s)" % ("install" if install else "check"))
    gc.collect()
    try:
        _connect_wifi()
        manifest = _get_json(source + "manifest.json" if source else _MANIFEST_URL)
    except Exception as e:
        print("Update: check failed:", e)
        _write_status(FAILED, error="check failed: %s" % e)
        return
    if _version_tuple(manifest["version"]) <= _version_tuple(VERSION):
        print("Update: up to date (%s)" % VERSION)
        _write_status(UP_TO_DATE)
    elif manifest.get("mpy") != sys.implementation._mpy & 0xFF:
        _write_status(FAILED, error="release needs another MicroPython version")
    elif install:
        _install(manifest, source)
    else:
        print("Update: %s available" % manifest["version"])
        _write_status(AVAILABLE, manifest)


def _install(manifest, source):
    import machine
    _rmtree(UPDATE_DIR)
    os.mkdir(UPDATE_DIR)
    files = manifest["files"]
    try:
        for i, f in enumerate(files):
            url = source + f["name"] if source else _FILE_URL % (REPO, manifest["version"], f["name"])
            for attempt in range(3):
                try:
                    gc.collect()
                    _download(url, UPDATE_DIR + "/" + f["name"], f["sha256"])
                    break
                except OSError as e:
                    print("Update: %s attempt %d failed: %s" % (f["name"], attempt + 1, e))
                    if attempt == 2:
                        raise
                    time.sleep_ms(1000)
            print("Update: %d/%d %s" % (i + 1, len(files), f["name"]))
    except Exception as e:
        _rmtree(UPDATE_DIR)
        _write_status(FAILED, manifest, "download failed: %s" % e)
        print("Update: download failed:", e)
        return
    with open(UPDATE_DIR + "/manifest.json", "w") as out:
        json.dump(manifest, out)
    with open(PENDING, "w") as out:
        out.write(manifest["version"])
    _write_status(RESTARTING, manifest)
    print("Update: %s downloaded, restarting to install" % manifest["version"])
    time.sleep_ms(300)
    machine.reset()


# --- in the running app ----------------------------------------------------------------


class Updater:
    """The update state for the app, the display and MQTT. check() and install()
    restart the board into a maintenance start."""

    def __init__(self, app):
        self.app = app
        try:
            status = json.loads(_read(STATUS_FILE) or "{}")
        except ValueError:
            status = {}
        self.state = status.get("state", IDLE)
        if self.state not in (AVAILABLE, FAILED, UP_TO_DATE):   # RESTARTING: that was us
            self.state = IDLE
        self.available = status.get("manifest") if self.state == AVAILABLE else None
        self.error = status.get("error") if self.state == FAILED else None
        self.progress = 0
        self._restart_at = None
        self._night_done = None
        self.source = _read(SOURCE_FILE) or None
        bad = self.available and self.available["version"] == _read(BAD_FILE)
        if self.available and app.cfg["update"]["auto"] and not bad:
            print("Update: installing %s automatically" % self.available["version"])
            self.install()

    def _restart_for(self, flag, state):
        with open(flag, "w") as f:
            f.write("1")
        self.state, self.error = state, None
        self._restart_at = time.ticks_add(time.ticks_ms(), 1500)   # let the app hear it first

    def check(self):
        if self._restart_at is None:
            self._restart_for(CHECK_FLAG, CHECKING)

    def install(self):
        if self.available and self._restart_at is None:
            self._restart_for(INSTALL_FLAG, DOWNLOADING)

    def dismiss(self):
        if self.state in (AVAILABLE, FAILED, UP_TO_DATE):
            self.state, self.error = IDLE, None
            _write_status(IDLE)   # the next nightly check offers it again

    def set_source(self, url):
        """Testing: a base URL instead of GitHub (None = GitHub again)."""
        self.source = url
        if url:
            with open(SOURCE_FILE, "w") as f:
                f.write(url)
        else:
            _remove(SOURCE_FILE)

    def poll(self):
        if self._restart_at is not None:
            if time.ticks_diff(time.ticks_ms(), self._restart_at) >= 0:
                import machine
                print("Update: restarting for the %s" % ("install" if self.state == DOWNLOADING else "check"))
                machine.reset()
            return
        app = self.app
        local = app.clock.local() if app.clock else None
        # Nightly check, unless a phone is connected (it would lose the link).
        if (local is not None and local[3] == _CHECK_HOUR and local[4] >= 30 and self._night_done != local[7]
                and app.online() and not (app.ble and app.ble.connection is not None)
                and not (app.selfcal and app.selfcal.running)):
            self._night_done = local[7]
            self.check()

    def status(self):
        a = self.available or {}
        return {"state": STATES[self.state], "progress": self.progress, "version": VERSION,
                "auto": self.app.cfg["update"]["auto"], "available": a.get("version"),
                "notes": a.get("notes"), "error": self.error, "source": self.source}
