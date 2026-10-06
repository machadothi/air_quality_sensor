# MQTT requests: send the text to the request topic (esp/<client_id>/request),
# the JSON answer arrives on the response topic (esp/<client_id>/response).
# app.py loads this module per request and drops it again, to save RAM.
import gc
import json
import time

from app import PAGE_NAMES, SETTINGS_FILE   # already loaded, costs nothing

REQUESTS = ("/read_all", "/status", "/display", "/display/next", "/topics", "/reboot")
_DISPLAY_USAGE = '/display {"pages": [...], "page_s": 1-60}'


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
        if (not isinstance(pages, list) or not pages or [p for p in pages if p not in PAGE_NAMES]
                or not isinstance(page_s, (int, float)) or not 1 <= page_s <= 60):
            return {"error": _DISPLAY_USAGE, "available": PAGE_NAMES}
        cfg["pages"], cfg["page_s"] = pages, page_s
        if app.display:
            app.display.set_pages(pages)
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"display": {"pages": pages, "page_s": page_s}}, f)
        print("Display:", pages, "every", page_s, "s")
    return {"present": app.display is not None, "pages": cfg["pages"], "page_s": cfg["page_s"],
            "available": PAGE_NAMES}


def handle(app, text):
    net = app.net
    if text in ("/read", "/read_all", "/read/air_quality_sensor"):
        return app.state_message()
    if text == "/status":
        return {"ip": net.ip(), "wifi_rssi": net.rssi(), "uptime_s": time.time() - app.boot_s,
                "free_ram": gc.mem_free(), "lowest_free_ram": app.min_free,
                "sensor_errors": app.air.errors, "sensor_state": app.sensor_state()}
    if text == "/display" or text.startswith("/display {"):
        return _display(app, text)
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
