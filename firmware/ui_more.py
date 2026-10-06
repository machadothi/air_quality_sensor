# Extra display pages, ESP32 only (the ESP8266 has no RAM to spare for them):
#   dewpoint  dew point (big), absolute humidity and a comfort word
#   sensor    ENS160 details: state, raw resistances, compensation in use, firmware
#   system    Wi-Fi signal, IP, MQTT/Bluetooth links, uptime
#   clock     local time, big; weekday and date
#   weather   Open-Meteo: temperature, condition, today's high/low (weather.py)
# weather needs the internet: it's skipped while the board is offline
# (App.online()), and so should any future internet-dependent page. The clock
# also shows offline once the time was set from the phone or by hand.
# register() adds them to ui's page table, before the Display is created.
import assets
import gfx
import sensors

_APP = None


def register(ui, app):
    global _APP
    _APP = app
    ui._PAGES["dewpoint"] = ("Dew point", assets.ICON_DEW, page_dewpoint)
    ui._PAGES["sensor"] = ("Air sensor", assets.ICON_CHIP, page_sensor)
    ui._PAGES["system"] = ("System", assets.ICON_ANTENNA, page_system)
    ui._PAGES["clock"] = ("Clock", assets.ICON_CLOCK, page_clock)
    ui._PAGES["weather"] = (_weather_title, _weather_icon, page_weather)
    ui.STATUS_ICONS.append(lambda: assets.ICON_UPDATE if app.updater and app.updater.state == 2 else None)
    ui._NEEDS["clock"] = lambda air: app.clock is not None and app.clock.known() and (app.online() or app.clock.trusted())
    ui._NEEDS["weather"] = lambda air: app.online() and app.weather is not None and app.weather.fresh()


def _rows(fb, rows, y=17):
    """Label left, value right, 11 px apart (four fit below the header)."""
    for label, value in rows:
        gfx.text(fb, assets.SMALL, label, 0, y)
        gfx.text_right(fb, assets.SMALL, value, 128, y)
        y += 11


def comfort(dew):
    """How the air feels, from the dew point (short: it shares a row)."""
    if dew is None:
        return "--"
    if dew < 5:
        return "Dry"
    if dew < 13:
        return "Pleasant"
    if dew < 16:
        return "Humid"
    if dew < 19:
        return "Very humid"
    return "Muggy"


def _ohms(raw):
    if raw is None:
        return "--"
    r = 2 ** (raw / 2048)   # ENS160 datasheet, section 7
    if r >= 1e6:
        return "%.2f MΩ" % (r / 1e6)
    if r >= 1e3:
        return "%.1f kΩ" % (r / 1e3)
    return "%d Ω" % r


def page_dewpoint(fb, air, net, history):
    import ui
    dew = sensors.dew_point(air.temperature, air.humidity)
    ui._big_value(fb, dew, 1, "°C")
    absolute = sensors.absolute_humidity(air.temperature, air.humidity)
    gfx.text(fb, assets.SMALL, "--" if absolute is None else "%.1f g/m³" % absolute, 0, 47)
    gfx.text_right(fb, assets.SMALL, comfort(dew), 128, 47)


def page_sensor(fb, air, net, history):
    state = sensors.VALIDITY_NAMES[air.validity] if air.validity is not None else "no sensor"
    fw = air.firmware
    _rows(fb, (
        ("State" if fw is None else "v%d.%d.%d" % fw, state),   # ENS160 firmware, and its state
        ("R1", _ohms(air.r1_raw)),
        ("R4", _ohms(air.r4_raw)),
        ("Uses", "--" if air.comp_t is None else "%.1f°C %.0f%%" % (air.comp_t, air.comp_rh)),
    ))


def page_system(fb, air, net, history):
    links = []
    if net.mqtt_ok:
        links.append("MQTT")
    if _APP.ble and _APP.ble.connection is not None:
        links.append("BT")
    up = _APP.uptime_s()
    _rows(fb, (
        ("Wi-Fi", "%d dBm" % net.rssi() if net.wifi_ok else "offline"),
        ("IP", net.ip() if net.wifi_ok else "--"),
        ("Links", " · ".join(links) if links else "none"),
        ("Uptime", "%dh %02dm" % (up // 3600, up % 3600 // 60) if up >= 3600 else "%d min" % (up // 60)),
    ))


def page_clock(fb, air, net, history):
    import clock
    t = _APP.clock.local() if _APP.clock else None
    if t is None:
        gfx.text_center(fb, assets.BIG, "--:--", 18)
        gfx.text_center(fb, assets.SMALL, "time not set yet", 47)
        return
    gfx.text_center(fb, assets.BIG, "%02d:%02d" % (t[3], t[4]), 18)
    gfx.text_center(fb, assets.SMALL, "%s %d %s %d" % (clock.DAYS[t[6]], t[2], clock.MONTHS[t[1] - 1], t[0]), 47)


def _weather_title():
    place = _APP.weather.cfg["place"] if _APP.weather else ""
    return place[:14] or "Weather"


def _weather_icon():
    import weather
    now = _APP.weather.now if _APP.weather else None
    if now is None:
        return assets.ICON_CLOUD
    name = weather.describe(now["code"])[1]
    return getattr(assets, "ICON_" + name.upper(), assets.ICON_CLOUD)


def page_weather(fb, air, net, history):
    import ui
    import weather
    w = _APP.weather
    now = w.now if w and w.fresh() else None
    if now is None:
        gfx.text_center(fb, assets.MID, "No weather", 20)
        gfx.text_center(fb, assets.SMALL, "set a place in the app" if not w.cfg["place"] else "waiting for data", 40)
        return
    ui._big_value(fb, now["temperature"], 0, "°C")
    gfx.text(fb, assets.SMALL, weather.describe(now["code"])[0], 0, 47)
    gfx.text_right(fb, assets.SMALL, "%d° / %d°" % (round(now["high"]), round(now["low"])), 128, 47)
