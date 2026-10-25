# Changelog

Each version's section is the release notes the board and the app show
(`tools/release.py` copies it into the release's `manifest.json`).

## 1.0.1

Pairing without a code, signed updates, works offline, gentler on Wi-Fi,
restarts itself if it hangs.

- Fix: the board restarted over and over when its Wi-Fi network wasn't
  available (or none was set), so Bluetooth was unusable and no other network
  could be chosen from the app. Wi-Fi errors no longer stop the board, and
  "Choose network" works while it's still trying to connect
- Works fully offline: without Wi-Fi, a network, a broker or even a
  config.json, the board measures, shows and talks Bluetooth as usual; only
  the internet features (MQTT, clock sync, weather, updates) wait for a
  connection. A network can then be chosen in the app
- "Check now" without Wi-Fi says so instead of restarting the board
- A bad write from a phone over Bluetooth no longer restarts the board
- Fix: a board that couldn't join its network (wrong password, a security
  mode it can't do) re-joined every ~12 s forever and flooded the router.
  Retries now back off from 30 s to 30 minutes, a refused password waits 10
  minutes, and the Wi-Fi driver's own retries are capped. Choosing a network
  or scanning in the app still tries at once
- Hardware watchdog (ESP32): a board that hangs anywhere, also inside the
  Bluetooth or network stack, restarts by itself within a minute (it used to
  freeze on one display page). The REPL and deploys still work after Ctrl+C
- Fix: with a display connected, a board that had run older firmware crashed
  at start-up (an old display driver without rotate()); `tools/deploy.sh`
  replaces it

- Self-heating measurement: the whole board switches off (deep sleep) for
  5 minutes (`cooldown_min`), and the first temperature after waking gives
  the offset

Security (see SECURITY.md):
- Updates must be signed with the release key; the board checks the
  signature and then every file's name, size and SHA-256. Unsigned, altered
  or oversized releases are refused
- Bluetooth: only bonded phones stay connected and can change settings.
  Pairing needs no code, but only works in the first 2 minutes after the
  board starts (reset button or power), 10 while no phone is bonded yet, or
  after "Add a phone" on a bonded phone.
  Readings stay public (BTHome). A factory reset forgets paired phones
- Weather replies, MQTT messages and Bluetooth writes are size-limited and
  validated
- Fix: with Wi-Fi up but no internet, the place lookup was retried on every
  loop pass, stalling the display; now every 5 minutes

## 1.0.0

First release.

- Air quality (ENS160), temperature and humidity (AHT21) on an ESP32 or ESP8266
- OLED pages: air quality, eCO2, TVOC, temperature, humidity, dew point, sensor
  details, system, clock, weather; chosen, ordered, timed and rotated from the app
- Bluetooth LE: BLE Sensor app support and BTHome for Home Assistant
- Wi-Fi and MQTT (switchable), Home Assistant discovery
- Temperature calibration: manual offset or a self-heating measurement, nightly
- Clock (internet, phone, or set by hand in the app; time zones with summer
  time) and Open-Meteo weather with automatic location
- Over-the-air updates from GitHub releases, installed after confirmation in
  the app, with automatic rollback
