# Home Assistant MQTT discovery: announces the readings so they appear in HA as
# one device ("Air Monitor") without any YAML. Turned on with
# "mqtt": {"home_assistant_discovery": true} in config.json.
#
# The messages are retained, so HA finds the device again after its own
# restarts. To remove the device from HA, publish an empty retained message to
# each homeassistant/sensor/air_monitor_<chip id>/.../config topic.
#
# net.py loads this module right after each MQTT connect and drops it again.
import machine

# key in the state JSON, name in HA, unit, HA device class
_SENSORS = (
    ("temperature", "Temperature", "°C", "temperature"),
    ("humidity", "Humidity", "%", "humidity"),
    ("eco2", "eCO2", "ppm", "carbon_dioxide"),
    ("tvoc", "TVOC", "ppb", "volatile_organic_compounds_parts"),
    ("aqi", "Air quality index", None, "aqi"),
    ("dew_point", "Dew point", "°C", "temperature"),
    ("absolute_humidity", "Absolute humidity", "g/m³", "absolute_humidity"),
)


def announce(net):
    cfg = net.cfg
    node = "air_monitor_" + machine.unique_id().hex()
    device = {"ids": [node], "name": cfg["device_name"], "mf": "DIY", "mdl": "ESP8266 + ENS160 + AHT21"}

    def config(key, name):
        return {"name": name, "uniq_id": node + "_" + key, "stat_t": cfg["topic_state"],
                "val_tpl": "{{ value_json.%s }}" % key, "avty_t": net.topic_availability,
                "dev": device}

    for key, name, unit, device_class in _SENSORS:
        message = config(key, name)
        message["dev_cla"] = device_class
        message["stat_cla"] = "measurement"
        if unit:
            message["unit_of_meas"] = unit
        net.publish("homeassistant/sensor/%s/%s/config" % (node, key), message, retain=True)
    # The ENS160 state as text (normal / warm-up / start-up), as a diagnostic.
    message = config("state", "Sensor state")
    message["ent_cat"] = "diagnostic"
    net.publish("homeassistant/sensor/%s/state/config" % node, message, retain=True)
    print("MQTT: Home Assistant discovery sent")
