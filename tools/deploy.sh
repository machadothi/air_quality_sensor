#!/usr/bin/env bash
# Compile the air monitor and copy it to the board, then restart it.
#
#   tools/deploy.sh                 # code only; the board keeps its config.json
#   tools/deploy.sh --config        # also upload firmware/config.json
#   PORT=/dev/ttyUSB1 tools/deploy.sh
#
# Needs mpremote and mpy-cross matching the board's MicroPython (1.24.x):
#   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Modules are compiled to .mpy so the ESP8266 doesn't spend its ~35 KB of RAM
# compiling them at boot. main.py and boot.py stay as source (tiny).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-/dev/ttyUSB0}"
BIN="${VENV:-$ROOT/.venv}/bin"
MPREMOTE="$BIN/mpremote"
MPY_CROSS="$BIN/mpy-cross"
MODULES=(app net sensors ui gfx assets commands home_assistant ble)
# Files of the old firmware (esp_manager.py and friends) and stale sources,
# which would be imported instead of the .mpy files.
STALE=(esp_manager.py sensor_reader.py modules app.py net.py sensors.py ui.py gfx.py assets.py commands.py home_assistant.py ble.py)

[ -x "$MPREMOTE" ] && [ -x "$MPY_CROSS" ] || { echo "Missing mpremote/mpy-cross in $BIN, see the top of $0"; exit 1; }

BUILD="$ROOT/build"
rm -rf "${BUILD:?}" && mkdir -p "$BUILD"
for module in "${MODULES[@]}"; do
    # -O3 drops line numbers (tracebacks show none), which saves ~6% RAM.
    "$MPY_CROSS" -O3 -o "$BUILD/$module.mpy" "$ROOT/firmware/$module.py"
done
echo "Compiled: ${MODULES[*]}"

remote() { "$MPREMOTE" connect "$PORT" "$@"; }

# Stop the running program first; retry, since the old firmware could be
# sleeping and miss the first Ctrl+C.
for attempt in 1 2 3; do
    remote exec "print('ready')" >/dev/null 2>&1 && break
    sleep 2
done

for file in "${STALE[@]}"; do
    remote rm -r ":$file" >/dev/null 2>&1 || true
done
args=()
for module in "${MODULES[@]}"; do
    args+=(cp "$BUILD/$module.mpy" ":$module.mpy" +)
done
args+=(cp "$ROOT/firmware/assets.bin" :assets.bin + cp "$ROOT/firmware/boot.py" :boot.py + cp "$ROOT/firmware/main.py" :main.py)
if [ "${1:-}" = "--config" ]; then
    # firmware/config.json holds your Wi-Fi and MQTT passwords; it is git-ignored.
    [ -f "$ROOT/firmware/config.json" ] || { echo "No firmware/config.json: copy config.example.json and fill it in"; exit 1; }
    args+=(+ cp "$ROOT/firmware/config.json" :config.json)
fi
remote "${args[@]}"
# The ESP8266 firmware has the OLED driver built in; on the ESP32 it is a
# package from micropython-lib (downloaded by mpremote, needs internet).
remote exec "import ssd1306" >/dev/null 2>&1 || remote mip install ssd1306
remote reset
echo "Deployed. Log: $MPREMOTE connect $PORT repl   (Ctrl+C stops the program, Ctrl+] quits)"
