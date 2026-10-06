# Firmware updates and releases (ESP32)

An ESP32 board updates itself from this repository's
[GitHub releases](https://github.com/machadothi/air_quality_sensor/releases).
It checks every night, and a new version is installed only after you say yes
in the BLE Sensor app, unless you allow automatic updates. If a new version
doesn't start properly, the board goes back to the old one by itself.

The ESP8266 can't do this (not enough RAM for HTTPS); update it with
`tools/deploy.sh`.

- [Using it](#using-it)
- [How it works](#how-it-works)
- [Making a release](#making-a-release)
- [Testing an update without GitHub](#testing-an-update-without-github)
- [Files on the board](#files-on-the-board)

## Using it

**In the BLE Sensor app** (Settings → Firmware):
- **The version** the board runs, and the outcome of the last check.
- **Check now.** The board restarts to check, which takes about 30 s. The app
  reconnects by itself.
- **When an update is available,** the app asks: *Update to 1.1.0?*, with the
  release notes.
  - **Install:** the board restarts, downloads and installs, which takes about
    a minute. The app reconnects when the board is back.
  - **Later:** the board stops offering this update until its next check.
- **Install automatically.** With this switch on, new versions install at
  night without asking.

**On the display**, an arrow-into-tray icon in the header means an update is
waiting for your answer.

**Over MQTT** (the request topic, see [communication.md](communication.md#requests)):

| Request | Does |
|---|---|
| `/update` | status: `state`, `version`, `available`, `notes`, `error`, `auto` |
| `/update check` | check now (the board restarts) |
| `/update install` | install the available update (the board restarts) |
| `/update auto on` / `auto off` | automatic installs |

**In `config.json`:** `"update": {"auto": false}`. The app's switch is stored in
`settings.json` and wins.

## How it works

The code is in `firmware/updater.py` and `firmware/boot.py`.

**Why the board restarts to check.**
- GitHub only speaks HTTPS.
- A TLS connection needs about 40 KB of the ESP32's internal RAM.
- With Bluetooth, MQTT and the display running, that RAM isn't there: the
  connection fails with `ENOMEM`.

So a check or an install happens in a short *maintenance start* instead:
1. The request (app, MQTT, the nightly check at 03:30) leaves a marker file
   (`/update_check` or `/update_install`) and restarts the board.
2. `main.py` calls `updater.maintenance()` before loading the app, while all
   the RAM is free.
3. `maintenance()` connects to Wi-Fi and fetches
   `https://github.com/machadothi/air_quality_sensor/releases/latest/download/manifest.json`.
   It writes the outcome to `/update_status.json`, which the app shows after
   the restart.

The nightly check is skipped while a phone is connected (it would lose the
link) or a self-heating measurement is running.

**Installing:**
1. Every file in the manifest is downloaded into `/update/`.
   - Each one's SHA-256 is checked; a mismatch or any error abandons the
     update, and the old version keeps running.
   - Three attempts per file.
   - Downloads stream to flash, never to RAM. MicroPython's `requests` can't
     follow GitHub's redirects or chunked replies, so `updater.py` has a small
     HTTP client of its own.
2. `/update_pending` is written, and the board restarts.
3. `boot.py` moves the old files to `/previous/` and the new ones into place.
4. It writes `/update_trial`, which counts the starts.

**Rollback:**
- The app deletes `/update_trial` after 60 s of normal running: the update
  is confirmed (`Update confirmed: 1.1.0` in the log).
- If that doesn't happen within two starts, `boot.py` puts `/previous/` back.
- A new version that can't even be imported makes `main.py` restart rather
  than stop at the REPL, so this rollback still happens.
- The version is recorded in `/update_bad` and never installed automatically
  again. The app shows "1.1.0 didn't start, rolled back".

**Compatibility:**
- A release is compiled `.mpy` code for one MicroPython version
  (`"mpy": 6` = MicroPython 1.24).
- A board on a different version refuses it rather than installing code it
  can't run.
- `config.json` and `settings.json` are never part of a release, so your
  network, broker and app settings stay.

## Making a release

1. **Note the changes** in `CHANGELOG.md` under a `## 1.1.0` heading. That
   section becomes the release notes the app shows.
2. **Build:**
   ```sh
   .venv/bin/python tools/release.py 1.1.0
   ```
   This does four things:
   - writes the version into `firmware/version.py`;
   - compiles every module (the list in `tools/deploy.sh`) with `mpy-cross -O3`;
   - collects them with `assets.bin`, `boot.py` and `main.py` in
     `dist/v1.1.0/`;
   - writes `manifest.json` (version, notes, `.mpy` format, each file's size
     and SHA-256);
   - writes the release notes to `dist/notes-v1.1.0.md`, for the GitHub release
     page.

   `dist/` is git-ignored.
3. **Commit** `version.py` and `CHANGELOG.md`, then tag and push:
   ```sh
   git commit -am "Release 1.1.0"
   git tag v1.1.0 && git push origin main v1.1.0
   ```
4. **Publish the release** with every file of `dist/v1.1.0/` attached:
   - **with the [GitHub CLI](https://cli.github.com):**
     `gh release create v1.1.0 dist/v1.1.0/* --title v1.1.0 --notes-file dist/notes-v1.1.0.md`;
   - **on github.com:** Releases → *Draft a new release* → tag `v1.1.0` → paste
     `dist/notes-v1.1.0.md` as the description → drag in every file of
     `dist/v1.1.0/` → *Publish release*.

   The release must be the *latest* one (not a draft or pre-release): boards
   look only at `releases/latest`.
5. **Check:** in the app, Settings → Firmware → *Check now*.

The files must keep their names: the board fetches
`releases/download/v1.1.0/<name>`.

## Testing an update without GitHub

Serve a release from the PC and point the board at it:

```sh
cd dist && python3 -m http.server 8000      # serves dist/v1.1.0/ ...
```
```
/update source http://<pc-ip>:8000/v1.1.0/     (MQTT request)
/update check
```

- **The source is stored on the board** (`/update_source`) until you send
  `/update source` without a URL, which goes back to GitHub.
- **To try the rollback,** build a release whose `app.py` raises an exception
  at import (do this in a copy of the repository) and install it.
- **Watch the log** with `mpremote connect /dev/ttyUSB0 repl`.

## Files on the board

| File | Written by | Meaning |
|---|---|---|
| `/update_check`, `/update_install` | the app (updater.py) | do this in the next maintenance start |
| `/update_status.json` | maintenance start, boot.py | the last outcome, shown by the app |
| `/update/` | maintenance start | the downloaded files, until boot.py installs them |
| `/update_pending` | maintenance start | install `/update/` at the next boot |
| `/previous/` | boot.py | the files the last update replaced |
| `/update_trial` | boot.py | starts of a new version not yet confirmed |
| `/update_bad` | boot.py | the version last rolled back |
| `/update_source` | `/update source` | testing: a URL instead of GitHub |
