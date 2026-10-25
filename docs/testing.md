# Testing

There are two test suites, both run with pytest:

| Suite | Where | Needs | Time | Runs |
|---|---|---|---|---|
| **PC tests** | `tests/` | nothing but Python | ~20 s | every push and pull request (GitHub Actions) |
| **Hardware tests** | `tests/hardware/` | the test board on USB, Bluetooth on the PC, the release key | ~10 min | by hand, before a release |

```sh
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest                                         # PC tests (hardware tests skip)
.venv/bin/pytest tests/hardware --board /dev/ttyUSB0     # the real board
```

## PC tests

These run the **real firmware**, not copies of it, under CPython.
`tests/fakes.py` stands in for MicroPython's hardware modules:

| Fake | Behaves like |
|---|---|
| `machine` | I2C with no chips unless a test adds one (`fakes.FakeAHT21`), `reset()` raises `fakes.Reset`, `deepsleep()` raises `fakes.DeepSleep`, `board.reset_cause`, RTC |
| `network` | the ESP32 Wi-Fi driver: retries by itself, refuses a second `connect()` and scans while connecting; networks in range are `board.networks` |
| `bluetooth` | records the registered service and flags, settings, security requests and disconnects; `board.ble.phone_connects(bond="known")` / `(pair_as=b"key")` and `phone_writes(handle, value)` play a phone |
| `umqtt.simple` | a broker that's up or down; `MQTTClient.inbox` delivers messages or raises errors |
| `time` | a clock the tests control: `board.ms`, and the RTC from 2000 like MicroPython |
| `requests`, `ntptime` | no internet unless a test replaces `requests.get` |
| `framebuf`, `ssd1306` | `tools/sim/`, the same as the screen preview |

**Fixtures** (`tests/conftest.py`):
- `board`: a fresh fake board. The test's working folder is its flash, with
  `assets.bin` in it.
- `firmware("app")`: imports a firmware module as an ESP32 would.
- `config({...})`: writes `config.json`.
- `run(app, seconds)`: runs the real main loop for that long in fake time.

**What is covered:**

| File | What |
|---|---|
| `test_offline.py` | starting without or with a broken `config.json`; the network gone for 3 minutes; scanning and choosing a network over Bluetooth; no broker; *Check now* without internet |
| `test_updates.py` | signed vs. tampered, forged or missing signatures; bad file names, sizes and hashes; downloads larger or different than announced; oversized manifests; a whole maintenance check |
| `test_ble_security.py` | writes need an encrypted, bonded link and readings stay public; the pairing window (first setup, 2 minutes after every start, "add a phone", closing, on the display); strangers dropped and refused new bonds outside it; bonded phones stay; bonds persisted, bounded and forgotten on factory reset; 300 random writes |
| `test_selfcal.py` | the self-heating measurement: the board switches off (deep sleep), the first reading after waking gives the offset; reset during the sleep, a warmer room, cancel |
| `test_untrusted_input.py` | malformed and oversized MQTT messages; MQTT read errors; spoofed weather and location replies; failed lookups spaced out |

**Writing a test:**

```python
def test_something(board, firmware, config, run):
    board.networks = {"Home": "pw"}                  # in range
    config({"wifi": {"ssid": "Home", "password": "pw"}})
    app = firmware("app").App()
    run(app, 30)                                     # 30 s of the main loop
    assert app.net.wifi_ok
```

## Hardware tests

These drive the real board through its USB serial port: the log, the REPL
and files on its flash. They use Bluetooth from this PC through bleak and
`bluetoothctl`.

**They need:**
- **The test board** on USB, with its sensors and display. Use a test board,
  not one in use: the tests factory-reset it and install test releases. The
  board must have a `config.json` with a reachable Wi-Fi network, or the
  update tests skip.
- **Bluetooth on the PC** (BlueZ) and `bluetoothctl`.
- **The release key** (`tools/signing_key.py show`): the test releases are
  signed with it.
- **The board and the PC on the same network:** the update tests serve
  releases from the PC.

**What they do, in order:**
1. **Start-up:** the board starts with this checkout's firmware
   (`tools/deploy.sh`), finds the AHT21 and ENS160, and
   runs 20 s without errors.
2. **Bluetooth:**
   - readings can be read without pairing;
   - first setup: with no phone bonded, the pairing window opens for 10
     minutes;
   - pairing without a code in the window works (`bluetoothctl`), and writes
     work afterwards;
   - an unpaired phone is dropped outside the window, and its writes are
     ignored;
   - the window closes 2 minutes after a start, and a restart opens it
     again;
   - a bonded phone connects any time and can open the window for another;
   - a factory reset forgets all phones.
3. **Without its network:** `config.json` points at a network that doesn't
   exist. The board runs 90 s without restarting and stays reachable over
   Bluetooth.
4. **Signed updates:**
   - The tests build three releases from a copy of the checkout: 99.0.0
     signed, 99.0.1 unsigned, 99.0.2 with a forged signature.
   - They serve them from the PC.
   - The signature check runs on the device, with its time measured.
   - The unsigned and forged releases are refused.
   - The signed one installs and is confirmed after 60 s.

**Afterwards** the board's `config.json`, `settings.json` and paired phones
are restored, and this checkout's firmware is deployed again (which undoes
the 99.0.0 test release). The PC's pairing is removed.

If a test fails, the board's log is in the failure message (the last lines
before the timeout).
