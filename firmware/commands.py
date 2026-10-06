# MQTT requests: send the text to the request topic (esp/<client_id>/request),
# the JSON answer arrives on the response topic (esp/<client_id>/response).
# app.py loads this module per request and drops it again, to save RAM.
import json
import time

from app import PAGE_NAMES   # already loaded, costs nothing

REQUESTS = ("/read_all", "/status", "/display", "/display/next", "/offset", "/calibrate", "/weather", "/update", "/topics", "/reboot")
_DISPLAY_USAGE = '/display {"pages": [...], "page_s": 1-60, "rotate": true/false}'


def _display(app, text):
    """/display: the current choice. /display {"pages": [...], "page_s": n}:
    change it (either key may be left out), applied at once and saved."""
    cfg = app.cfg["display"]
    if text != "/display":
        try:
            change = json.loads(text[9:])
        except ValueError:
            change = None
        if not isinstance(change, dict):
            return {"error": _DISPLAY_USAGE}
        pages = change.get("pages", cfg["pages"])
        page_s = change.get("page_s", cfg["page_s"])
        rotate = change.get("rotate", cfg["rotate"])
        if (not isinstance(pages, list) or not pages or [p for p in pages if p not in PAGE_NAMES]
                or not isinstance(page_s, (int, float)) or not 1 <= page_s <= 60
                or not isinstance(rotate, bool)):
            return {"error": _DISPLAY_USAGE, "available": PAGE_NAMES}
        cfg["pages"], cfg["page_s"], cfg["rotate"] = pages, page_s, rotate
        if app.display:
            app.display.set_pages(pages)
            app.display.set_rotate(rotate)
        app.save_settings()
        if app.ble:
            app.ble.write_display()   # keep the Bluetooth Display value in step
        print("Display:", pages, "every", page_s, "s")
    return {"present": app.display is not None, "pages": cfg["pages"], "page_s": cfg["page_s"], "rotate": cfg["rotate"],
            "available": PAGE_NAMES}


def handle(app, text):
    net = app.net
    if text in ("/read", "/read_all", "/read/air_quality_sensor"):
        return app.state_message()
    if text == "/status":
        status = app.system_info()
        air = app.air
        status.update({"lowest_free_ram": app.min_free, "sensor_errors": air.errors,
                       "sensor_integrity_errors": air.integrity_errors, "sensor_state": app.sensor_state(),
                       "ens160_firmware": air.firmware, "humid_s": air.humid_s})
        return status
    if text == "/display" or text.startswith("/display {"):
        return _display(app, text)
    if text == "/offset" or text.startswith("/offset "):
        # /offset: the temperature offset; /offset -2.0: set it (°C, -10 to 10)
        if text != "/offset":
            try:
                app.set_temperature_offset(float(text[8:]))
            except ValueError as e:
                return {"error": str(e)}
            if app.ble:
                app.ble.write_calibration()   # keep the Bluetooth value in step
        return {"temperature_offset": app.air.offset, "temperature": app.air.temperature}
    if text.startswith("/calibrate") and app.selfcal:
        # /calibrate: status; /calibrate start|cancel; /calibrate auto on|off
        cal, words = app.selfcal, text.split()[1:]
        if words == ["start"]:
            cal.start()
        elif words == ["cancel"]:
            cal.cancel()
        elif len(words) == 2 and words[0] == "auto" and words[1] in ("on", "off"):
            app.cfg["sensor"]["auto_calibration"] = words[1] == "on"
            app.save_settings()
        elif words:
            return {"error": "/calibrate [start | cancel | auto on | auto off]"}
        return cal.status()
    if text.startswith("/update") and app.updater:
        # /update: status; /update check | install
        u, rest = app.updater, text[7:].strip()
        if rest == "check":
            u.check()
        elif rest.startswith("source"):   # testing: "/update source <base url>" or "/update source" = GitHub
            u.set_source(rest[6:].strip() or None)
        elif rest == "install":
            u.install()
        elif rest in ("auto on", "auto off"):
            app.cfg["update"]["auto"] = rest == "auto on"
            app.save_settings()
        elif rest:
            return {"error": "/update [check | install]"}
        return u.status()
    if text.startswith("/weather") and app.weather:
        # /weather: status; /weather place <name> (or "auto"); /weather on|off|refresh
        w, rest = app.weather, text[8:].strip()
        if rest.startswith("place "):
            w.set_place(rest[6:])
        elif rest in ("on", "off"):
            w.cfg["enabled"] = rest == "on"
            app.save_settings()
        elif rest == "refresh":
            w.refresh()
        elif rest:
            return {"error": "/weather [place <name> | on | off | refresh]"}
        return {"enabled": w.cfg["enabled"], "place": w.cfg["place"], "auto_place": w.cfg.get("auto_place"),
                "online": app.online(),
                "now": w.now, "age_s": w.age_s(), "error": w.error}
    if text == "/display/next" and app.display:
        app.display.next_page(app.air, net, app.history)
        return {"page": app.display.pages[app.display.index]}
    if text == "/topics":
        return {"state": app.cfg["mqtt"]["topic_state"], "requests": net.topic_sub,
                "responses": net.topic_pub, "availability": net.topic_availability,
                "requests_accepted": REQUESTS}
    if text == "/reboot":
        app.reboot_at = time.ticks_add(time.ticks_ms(), 1000)   # after the answer is sent
        return {"rebooting": True}
    return {"error": "unknown request", "requests_accepted": REQUESTS}
