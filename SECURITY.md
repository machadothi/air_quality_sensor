# Security

How the air monitor protects itself and your home network, what it doesn't
protect, and how to report a problem.

## Reporting a problem

Please report security problems privately, via GitHub's *Report a
vulnerability* (Security tab of the repository), not as a public issue.

## What is protected

| Asset | Threat | Protection |
|---|---|---|
| Code on the board | a fake update (hostile network, DNS spoofing, a broker user with `/update source`, a compromised GitHub account) | releases are signed with a key that never leaves the release PC; the board checks the signature, then every file's name, size and SHA-256 ([updates.md](docs/updates.md#signed-releases)) |
| Settings, Wi-Fi, commands over Bluetooth | anyone within ~30 m connecting | only bonded phones stay connected and can write; pairing (no code, LE Secure Connections) is only possible for 2 minutes after the reset button is pressed twice, or from an already bonded phone; a factory reset forgets all phones ([bluetooth.md](docs/bluetooth.md#pairing-and-security)) |
| Wi-Fi password sent from the app | sniffing the Bluetooth link | the link is encrypted after pairing |
| The board running at all | malformed MQTT messages, spoofed weather replies, random Bluetooth writes, a missing network | every input is size-limited and validated; errors drop a connection, never stop the board (tests in `tests/`) |
| Wi-Fi, broker login in the repository | publishing them | `config.json` is git-ignored and never part of a release; the history was checked |
| Broker password in the MQTT phone app | copying the app's data | encrypted with an Android Keystore key, excluded from backups and device transfers |

## What is not protected (known limits)

- **MQTT is plain text.**
  - **Why:** the ESP32 doesn't have the RAM for TLS next to Bluetooth.
  - **The risk:** anyone on your network can read the readings and the
    broker login, and send requests (`/reboot`, `/display`, `/offset`,
    `/update install`, …).
  - **What to do:** keep the broker on your home network. Give the board its
    own broker user, with an ACL limited to `esp/#`. Don't expose port 1883 to
    the internet.
- **BTHome broadcasts are not encrypted.** Anyone nearby can read the
  temperature, humidity and CO2, which can show whether someone is home.
  Turn them off with `"bluetooth": {"bthome": false}` if that matters.
- **Physical access is full access.** Over USB anyone can open the
  MicroPython REPL and read `config.json`, `settings.json` (Wi-Fi and broker
  passwords) and the pairing keys. MicroPython has no flash encryption or
  secure boot.
- **Pairing has no code.** While the pairing window is open (2 minutes after
  a double press of the reset button, or 10 minutes after start-up while no
  phone is bonded yet), anyone in range can pair. Open it only when you're
  pairing your own phone, and check the app shows it paired.
- **Unpaired phones can connect for a few seconds** before the board drops
  them (MicroPython can't advertise to bonded phones only). In that time they
  can read the public readings, the same values BTHome broadcasts.
- **Weather and location travel over plain HTTP** (Open-Meteo, ip-api.com).
  A spoofed reply can show wrong weather, but every value is checked, so it
  can't do more than that.
- **The internet-time clock (NTP) isn't authenticated.** A wrong time only
  moves the nightly check and calibration.

## For maintainers

- **The release key:**
  - Create it once with `tools/signing_key.py new`.
  - Keep `~/.config/air_quality_sensor/release-key.pem` private, with a copy
    offline.
  - See [updates.md](docs/updates.md#signed-releases) for losing or replacing
    it.
- **Tests:** `.venv/bin/pytest` runs the firmware on the PC with
  MicroPython stand-ins (`tests/fakes.py`), the security behaviour included.
  CI runs them on every push and pull request.
- **Before a release:** run `tools/signing_key.py show`. It must say
  "matches".
