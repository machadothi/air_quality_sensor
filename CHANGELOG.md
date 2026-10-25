# Changelog

Each version's section is the release notes the board and the app show
(`tools/release.py` copies it into the release's `manifest.json`).

## 1.0.1

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
