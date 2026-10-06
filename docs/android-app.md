# Android app

`android/` is a phone app for the air monitor. It talks to the board **through
the MQTT broker**: the ESP8266 has no Bluetooth, and it already publishes
everything over MQTT. So the app works anywhere the broker is reachable,
normally your home network.

- [Screens](#screens)
- [Build and install](#build-and-install)
- [First start](#first-start)
- [How it works](#how-it-works)
- [Code map](#code-map)
- [Troubleshooting](#troubleshooting)

## Screens

| Screen | What it does |
|---|---|
| **Connect** | broker address, port, username, password and the board's client id; "Forget these settings". On later starts it connects by itself with the saved settings. |
| **Live** | air-quality rating (Excellent … Unhealthy) on a half-circle gauge whose needle springs to the current index; eCO2, TVOC, temperature and humidity cards with animated numbers, a short verdict ("Fresh", "Getting stuffy", "Comfortable", …) and a chart since the app connected. While the ENS160 warms up, a light sweeps along the gauge. |
| **Display** | what the board's OLED shows: a switch per page, arrows to change the order, "Each page for" 1–60 s, "Next page". A small animated preview cycles through the chosen pages at the chosen pace. |
| **Device** | IP, Wi-Fi signal, uptime, free RAM (now and lowest), sensor state and errors; the MQTT topics in use; "Restart the board" (with confirmation). |

The top bar shows the connection: broker first (connecting / reconnecting /
failed), then the board (online / offline / "updated 12 s ago").

## Build and install

Same toolchain as the BLE Sensor app (`~/git/BLE_Sensor/android`): Android
SDK in `~/Android/Sdk`, JDK 21. The Gradle wrapper downloads Gradle 9.8 and all
libraries on the first build.

```sh
cd android
export JAVA_HOME=~/git/BLE_Sensor/tools/jdk        # or any JDK 21
./gradlew assembleDebug testDebugUnitTest
~/Android/Sdk/platform-tools/adb install -r app/build/outputs/apk/debug/app-debug.apk
```

| Library | Version | Used for |
|---|---|---|
| Kotlin / AGP / Gradle | 2.4.20 / 9.4.1 / 9.8 | build |
| Jetpack Compose (BOM 2026.09.00), Material 3 | | UI |
| Hilt | 2.60.1 | dependency injection |
| Navigation Compose | 2.10.2 | Connect → Monitor |
| kotlinx.serialization | 1.11.0 | JSON messages, navigation routes |
| **Eclipse Paho MQTT** (`org.eclipse.paho.client.mqttv3`) | 1.2.5 | MQTT 3.1.1 client |
| DataStore Preferences | 1.2.1 | the saved broker settings |

Versions live in `android/gradle/libs.versions.toml`.

## First start

1. Open the app and fill in:
   - **Address:** the broker's IP (your Home Assistant host, if you use its
     Mosquitto add-on), port 1883.
   - **Username / password:** a broker login. Any MQTT user that may read
     `esp/#` and write `esp/<client id>/request` works. A dedicated user for
     the app is better than reusing the board's.
   - **Board's client id:** `mqtt.client_id` from the board's `config.json`.
2. Tap **Connect**. The settings are saved on the phone (app-private storage,
   excluded from backups) and never leave it, except to log in to your broker.
3. **GrapheneOS:** the app needs the **Network** permission (Settings → Apps →
   Air Monitor → Permissions). Without it the app says "Network access is
   blocked for this app".

## How it works

```
 phone app ──subscribe──► esp/air_quality_sensor          (readings, retained: shown at once)
           ──subscribe──► esp/<id>/response               (answers)
           ──subscribe──► esp/<id>/availability           (online / offline)
           ──publish────► esp/<id>/request                (/read_all every 5 s, /status every 30 s,
                                                            /display ..., /display/next, /reboot)
```

- **Fresh values.** The board publishes averages once a minute. While the
  Live screen is visible, the app also asks for `/read_all` every 5 s, so
  values move. Polling stops when the app goes to the background.
- **One response topic for all answers.** The app recognises an answer by its
  keys (`pages` → display, `uptime_s` → status, `temperature` → reading,
  `error` → shown as a message). See `AirProtocol.parseResponse`.
- **Display changes** are shown at once (optimistic). The board's answer then
  confirms them, or an error message appears and the app reloads the real
  state.
- **Reconnecting.** Paho reconnects by itself and the app subscribes again.
  The top bar says "reconnecting" meanwhile.
- **Each app start uses a new MQTT client id** (`air-monitor-app-xxxxxxxx`), so
  it never kicks another client off the broker.
- **Charts** keep the readings since the app connected: up to 720 points, one
  hour at one reading every 5 s. They are not stored.

The protocol itself is described in [communication.md](communication.md).

## Code map

`android/app/src/main/java/com/machadothi/airmonitor/`:

| File | Role |
|---|---|
| `mqtt/MqttConnection.kt` | Paho wrapped in coroutines/flows: connect, subscribe, publish, status, readable error messages |
| `data/AirProtocol.kt` | topics, requests, JSON message classes, display pages, AQI scale; mirrors `firmware/net.py` and `firmware/commands.py` |
| `data/BrokerSettings.kt` | the settings and their DataStore |
| `data/AirRepository.kt` | single source of truth: readings, history, status, display, online/offline, events |
| `ui/screen/connect/` | the Connect screen and its ViewModel |
| `ui/screen/monitor/` | `MonitorScreen` (top bar, tabs), `LiveTab` (gauge, cards), `DisplayTab` (pages, preview), `DeviceTab`; `MonitorViewModel` (polling) |
| `ui/components/` | shared with the BLE Sensor app: `GlowCard`, `AnimatedNumber`, `Sparkline`, `SignalBars`, `AppSwitch`, `LabeledSlider` |
| `ui/theme/` | the same dark instrument-panel theme |

Tests: `android/app/src/test/.../AirProtocolTest.kt` parses messages exactly
as the board sends them and checks the `/display` request format.

**Adding a request:** handle it in `firmware/commands.py`, add the text to
`AirProtocol`, recognise its answer in `parseResponse`, and expose it through
`AirRepository`.

## Troubleshooting

| Message | Meaning |
|---|---|
| "Network access is blocked for this app" | GrapheneOS Network permission is off |
| "Broker not reachable: are you on the home Wi-Fi?" | the phone is on mobile data or another network |
| "The broker refused the username or password" | wrong login, or that user isn't allowed |
| "Waiting for the board…" | connected to the broker, but nothing heard from the board: wrong client id, or the board is off |
| "Board offline" | the broker reported the board gone (its last will) |
| Display tab keeps spinning | the board doesn't answer `/display`: firmware older than this app, redeploy it |
