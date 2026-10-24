# Runs first at every boot. Besides tidying memory it counts reset-button
# presses (for Bluetooth pairing, see ble.py) and finishes an over-the-air
# update (see updater.py): it puts the downloaded files in place, and rolls them
# back if the new version doesn't run healthily within two starts (app.py
# deletes /update_trial after 60 s of normal running). Everything is wrapped so
# that a problem here never stops the board from starting.
import gc
import os


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _install():
    import json
    with open("/update/manifest.json") as f:
        manifest = json.load(f)
    if _exists("/previous"):
        for name in os.listdir("/previous"):
            os.remove("/previous/" + name)
    else:
        os.mkdir("/previous")
    for entry in manifest["files"]:
        name = entry["name"]
        if _exists("/" + name):
            os.rename("/" + name, "/previous/" + name)
        os.rename("/update/" + name, "/" + name)
    os.remove("/update/manifest.json")
    os.rmdir("/update")
    os.remove("/update_pending")
    with open("/update_trial", "w") as f:
        f.write("0 " + manifest["version"])
    print("Update installed:", manifest["version"])


def _trial():
    with open("/update_trial") as f:
        starts, _, version = f.read().partition(" ")
    starts = int(starts or 0)
    if starts >= 2:   # it never reached "healthy": back to the previous version
        for name in os.listdir("/previous"):
            os.rename("/previous/" + name, "/" + name)
        os.remove("/update_trial")
        # Tell the app, and never install this version automatically again.
        with open("/update_bad", "w") as f:
            f.write(version)
        with open("/update_status.json", "w") as f:
            f.write('{"state": 5, "manifest": null, "error": "%s didn\'t start, rolled back"}' % version)
        print("Update rolled back: the new version didn't start properly")
    else:
        with open("/update_trial", "w") as f:
            f.write("%d %s" % (starts + 1, version))


def _count_presses():
    """Counts reset-button presses in a row, for opening the Bluetooth pairing
    window (ble.py): every power-on start (the reset button, or power) adds one,
    any other start (software restart, crash, watchdog) starts again from zero.
    app.py deletes the count once the board has run a few seconds."""
    import machine
    if machine.reset_cause() != machine.PWRON_RESET:
        if _exists("/presses"):
            os.remove("/presses")
        return
    count = 0
    if _exists("/presses"):
        with open("/presses") as f:
            count = int(f.read() or 0)
    with open("/presses", "w") as f:
        f.write(str(count + 1))


try:
    _count_presses()
except Exception as e:
    print("boot: press count failed:", e)

try:
    if _exists("/update_pending") and _exists("/update/manifest.json"):
        _install()
    elif _exists("/update_trial"):
        _trial()
except Exception as e:
    print("boot: update step failed:", e)

gc.collect()
