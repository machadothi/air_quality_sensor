# Wi-Fi and MQTT, kept alive from the main loop: call poll() often. Nothing in
# here waits for the network, so the display keeps running while it is down.
#
# MQTT topics (names from config.json):
#   <topic_state>          readings as JSON, every publish_s, retained (default esp/air_quality_sensor)
#   <topic_sub>            requests, e.g. "/read_all", "/status"   (esp/<client_id>/request)
#   <topic_pub>            responses to requests, as JSON          (esp/<client_id>/response)
#   esp/<client_id>/availability   "online" / "offline" (retained; broker sends offline if we vanish)
#   homeassistant/...      Home Assistant discovery, if enabled (home_assistant.py)
import json
import sys
import time

import network
from umqtt.simple import MQTTClient, MQTTException

_KEEPALIVE_S = 60
_WIFI_RETRY_MS = 30000
_MQTT_RETRY_MIN_MS = 5000
_MQTT_RETRY_MAX_MS = 120000


class Net:
    def __init__(self, wifi_cfg, mqtt_cfg, on_request):
        self.cfg = mqtt_cfg
        self.on_request = on_request   # on_request(text) -> dict to answer with
        client_id = mqtt_cfg["client_id"]
        self.topic_sub = mqtt_cfg["topic_sub"].format(client_id=client_id)
        self.topic_pub = mqtt_cfg["topic_pub"].format(client_id=client_id)
        self.topic_availability = "esp/%s/availability" % client_id

        # The ESP8266 starts an open access point by default; nobody needs it.
        network.WLAN(network.AP_IF).active(False)
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self._ssid, self._password = wifi_cfg["ssid"], wifi_cfg["password"]
        self._wifi_retry = time.ticks_ms()
        self.mqtt = None
        self._mqtt_retry = time.ticks_ms()
        self._mqtt_backoff = _MQTT_RETRY_MIN_MS
        self._last_ping = 0
        self._was_wifi_ok = False
        print("Wi-Fi: connecting to", self._ssid)
        self.wlan.connect(self._ssid, self._password)

    # --- state -------------------------------------------------------------------

    @property
    def wifi_ok(self):
        return self.wlan.isconnected()

    @property
    def mqtt_ok(self):
        return self.mqtt is not None

    def rssi(self):
        try:
            return self.wlan.status("rssi")
        except (OSError, ValueError):
            return 0

    def ip(self):
        return self.wlan.ifconfig()[0]

    @property
    def ssid(self):
        return self._ssid

    def wifi_state(self):
        """(state, reason): state 0 idle, 1 connecting, 2 connected, 3 failed;
        reason when failed: 1 wrong password, 2 network not found, 3 other."""
        if self.wlan.isconnected():
            return 2, 0
        status = self.wlan.status()
        if status == network.STAT_CONNECTING:
            return 1, 0
        if status == getattr(network, "STAT_WRONG_PASSWORD", -1):
            return 3, 1
        if status == getattr(network, "STAT_NO_AP_FOUND", -1):
            return 3, 2
        if status == network.STAT_IDLE:
            return 0, 0
        return 3, 3

    def set_wifi(self, ssid, password):
        """Switch to another network (from the app)."""
        print("Wi-Fi: switching to", ssid)
        self._ssid, self._password = ssid, password
        self._drop_mqtt()
        try:
            self.wlan.disconnect()
        except OSError:
            pass
        self.wlan.connect(ssid, password)
        self._wifi_retry = time.ticks_add(time.ticks_ms(), 30000)
        self._was_wifi_ok = False

    def scan(self):
        """Networks in range, strongest first: [(name, rssi)], at most 10.
        Blocks for about 3 s."""
        best = {}
        for net in self.wlan.scan():
            name = net[0].decode("utf-8", "replace") if net[0] else ""
            if name and (name not in best or net[3] > best[name]):
                best[name] = net[3]
        return sorted(best.items(), key=lambda item: -item[1])[:10]

    # --- main loop -----------------------------------------------------------------

    def poll(self):
        now = time.ticks_ms()
        if not self.wifi_ok:
            if self._was_wifi_ok:
                print("Wi-Fi: lost")
                self._was_wifi_ok = False
            self._drop_mqtt()
            # The ESP8266 reconnects by itself; only kick it if it gave up.
            if (time.ticks_diff(now, self._wifi_retry) >= 0
                    and self.wlan.status() != network.STAT_CONNECTING):
                self._wifi_retry = time.ticks_add(now, _WIFI_RETRY_MS)
                self.wlan.connect(self._ssid, self._password)
            return
        if not self._was_wifi_ok:
            self._was_wifi_ok = True
            print("Wi-Fi: connected,", self.ip())

        if not self.cfg["enabled"]:   # switched off in the app
            return
        if self.mqtt is None:
            if time.ticks_diff(now, self._mqtt_retry) >= 0:
                self._connect_mqtt()
            return
        try:
            self.mqtt.check_msg()
            if time.ticks_diff(now, self._last_ping) >= _KEEPALIVE_S * 1000 // 2:
                self.mqtt.ping()
                self._last_ping = now
        except OSError as e:
            print("MQTT: lost:", e)
            self._drop_mqtt()

    def publish_state(self, state):
        # Retained, so a client that subscribes (e.g. the phone app) gets the
        # latest readings at once instead of waiting for the next publish.
        self.publish(self.cfg["topic_state"], state, retain=True)

    # --- MQTT ----------------------------------------------------------------------

    def _connect_mqtt(self):
        cfg = self.cfg
        print("MQTT: connecting to", cfg["server"])
        client = MQTTClient(cfg["client_id"], cfg["server"], port=cfg["port"],
                            user=cfg["username"], password=cfg["password"],
                            keepalive=_KEEPALIVE_S)
        client.set_callback(self._on_message)
        client.set_last_will(self.topic_availability, b"offline", retain=True)
        try:
            client.connect()
            client.subscribe(self.topic_sub)
            client.publish(self.topic_availability, b"online", retain=True)
        # MQTTException: broker refused (e.g. wrong password); IndexError: it closed the socket early
        except (OSError, MQTTException, IndexError) as e:
            try:
                client.sock.close()
            except Exception:
                pass
            self._mqtt_retry = time.ticks_add(time.ticks_ms(), self._mqtt_backoff)
            print("MQTT: failed (%s), retry in %d s" % (e, self._mqtt_backoff // 1000))
            self._mqtt_backoff = min(self._mqtt_backoff * 2, _MQTT_RETRY_MAX_MS)
            return
        self.mqtt = client
        self._mqtt_backoff = _MQTT_RETRY_MIN_MS
        self._last_ping = time.ticks_ms()
        print("MQTT: connected, requests on", self.topic_sub)
        if cfg["home_assistant_discovery"]:
            import home_assistant   # loaded only for this, then dropped (RAM)
            home_assistant.announce(self)
            del sys.modules["home_assistant"]

    def stop_mqtt(self):
        """Leave cleanly: tell the broker (and Home Assistant) we're offline."""
        if self.mqtt is None:
            return
        try:
            self.mqtt.publish(self.topic_availability, b"offline", True)
            self.mqtt.disconnect()
        except OSError:
            pass
        self._drop_mqtt()

    def _drop_mqtt(self):
        if self.mqtt is None:
            return
        try:
            self.mqtt.sock.close()
        except Exception:
            pass
        self.mqtt = None
        self._mqtt_retry = time.ticks_add(time.ticks_ms(), _MQTT_RETRY_MIN_MS)

    def publish(self, topic, payload, retain=False):
        """Publish payload (dict -> JSON); False if not connected."""
        if self.mqtt is None:
            return False
        try:
            self.mqtt.publish(topic, json.dumps(payload) if not isinstance(payload, (str, bytes)) else payload,
                              retain)
            return True
        except OSError as e:
            print("MQTT: publish failed:", e)
            self._drop_mqtt()
            return False

    def _on_message(self, topic, msg):
        text = msg.decode().strip()
        print("MQTT: request", text)
        self.publish(self.topic_pub, self.on_request(text))
