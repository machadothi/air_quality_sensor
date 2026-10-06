# Sensors

Both sensors are on the common ENS160 + AHT21 breakout. The drivers are in
`firmware/sensors.py`, written from the datasheets:
- ENS160: ScioSense datasheet SC-001224-DS
- AHT21: Aosong AHT21 datasheet (the AHT20 one is nearly identical)

## ENS160 — air quality (I2C 0x53)

A metal-oxide (MOX) gas sensor with four heated elements and its own
processor. From the gas readings it calculates:
- **TVOC** (ppb), total volatile organic compounds;
- **eCO2** (ppm), *equivalent* CO2. People breathe out CO2 and VOCs together,
  so CO2 is estimated from VOCs. It's not a real CO2 measurement (that needs
  an NDIR sensor such as the SCD40);
- **AQI**, 1–5, following the German UBA scale.

### Registers used

| Register | Name | Use |
|---|---|---|
| 0x00–0x01 | PART_ID | must read 0x0160, else "not found" |
| 0x10 | OPMODE | 0xF0 reset → 0x01 idle → 0x02 standard (measuring) |
| 0x11 | CONFIG | 0x00: no interrupt pin |
| 0x12 | COMMAND | 0xCC: clear the general-purpose registers; 0x0E: firmware version (idle mode only) |
| 0x13–0x16 | TEMP_IN, RH_IN | compensation: `(T + 273.15) × 64` and `RH × 512`, little-endian |
| 0x20 | DEVICE_STATUS | bit 7 running, bit 6 error, bits 3:2 validity, bit 1 new data |
| 0x21–0x25 | DATA_AQI, DATA_TVOC, DATA_ECO2 | read in one 5-byte burst |
| 0x30–0x33 | DATA_T, DATA_RH | the compensation the sensor actually uses; read every 10 s |
| 0x38 | DATA_MISR | checksum of the bytes read, see [Integrity check](#integrity-check) |
| 0x48–0x4F | GPR_READ | after 0x0E: firmware version (bytes 4–6); while measuring: raw resistances R1 (bytes 0–1), R4 (bytes 6–7) |

### Start-up sequence (`AirSensor._connect_ens`)

- **Cold start** (the sensor is idle after power-on): check PART_ID → reset →
  idle → clear CONFIG → clear GPR → read the **firmware version** (only possible
  in idle mode) → standard mode. The 3-minute warm-up follows.
- **Warm start** (the ESP restarted, but the sensor kept measuring): leave it
  alone. A reset would start the 3-minute warm-up again for nothing
  (datasheet 10.2). The firmware version comes from the ESP's RTC memory,
  where the cold start saved it.

The log says which: `ENS160 found, firmware 5.4.6` or `ENS160 found, still
running, firmware 5.4.6`.

### Validity: warm-up

| Validity | Name | When | What the firmware does |
|---|---|---|---|
| 0 | normal | | publishes AQI/TVOC/eCO2 |
| 1 | warm-up | first ~3 min after power-on | `null` over MQTT, "Warming up" + progress on the display, CO2/TVOC pages skipped |
| 2 | initial start-up | first ~1 h of a **new** sensor's life | same; the progress bar assumes 1 h |
| 3 | invalid | | same |

A brand-new ENS160 also keeps settling over its first 24 hours of operation.

Right after the reset the ENS160 briefly reports validity 0 ("normal") with all
readings 0, before its "running" bit (status bit 7) is set. The firmware
treats "not running" as warm-up, so those zeros are never published.

### Compensation

The gas readings depend on temperature and humidity. By default the ENS160
assumes 25 °C / 50 %. After each AHT21 reading, the firmware writes the real
values to TEMP_IN/RH_IN, so the ENS160 calculates with actual conditions.
DATA_T/DATA_RH read them back ("Uses" on the sensor page, "Compensation in
use" in the app): they should match the temperature and humidity shown.

### Raw resistances

The ENS160 has four metal-oxide elements; for two of them (1 and 4) it reports
the raw resistance, `R = 2^(raw / 2048)` Ω (datasheet section 7). They swing
widely, by design: the elements' heaters run in cycles. They're shown for
insight; the calibrated outputs are AQI, TVOC and eCO2.

### Integrity check

Every value read over I2C also feeds a running checksum in the sensor
(DATA_MISR, CRC with polynomial 0x1D, datasheet 16.2.14). The firmware keeps
its own copy and compares after each reading; a mismatch means a byte was
corrupted on the bus, so that reading is dropped and counted ("checksum
errors"). The datasheet says only registers 0x20–0x37 count; measured on a real
ENS160 (firmware 5.4.6), **every** read does, so the firmware counts all of them.

### Ratings

| eCO2 (ppm) | Rating (datasheet table 5) | | AQI (UBA) | TVOC (ppb) | Rating |
|---|---|---|---|---|---|
| 400–600 | excellent | | 1 | 0–65 | excellent |
| 600–800 | good | | 2 | 65–220 | good |
| 800–1000 | fair: ventilation optional | | 3 | 220–660 | moderate |
| 1000–1500 | poor: ventilate | | 4 | 660–2200 | poor |
| > 1500 | bad: ventilation required | | 5 | 2200–5500 | unhealthy |

**TVOC in µg/m³.** The ENS160's TVOC is ethanol-calibrated (its DATA_ETOH
register mirrors DATA_TVOC), so `µg/m³ = ppb × 46.07 / molar volume`, with the
molar volume at the current temperature (24.5 L at 25 °C). That's what BTHome
sends and the app shows.

## AHT21 — temperature and humidity (I2C 0x38)

| Step | Bytes | Notes |
|---|---|---|
| status | read 1 | bit 3 = calibrated; if not: send `BE 08 00` (init) |
| measure | write `AC 33 00` | then wait ≥ 80 ms |
| result | read 7 | status, 20-bit humidity, 20-bit temperature, CRC |

- **Non-blocking.** One `update()` sends the command; a later one, 80 ms or
  more later, reads the result. Nothing sleeps.
- **Busy and CRC checks.** If the busy bit (status bit 7) is set or the CRC
  (CRC-8, polynomial 0x31, initial value 0xFF) is wrong, the reading is
  dropped.
- **Every 2 s, not faster.** The datasheet warns that more frequent
  measurements heat the sensor itself.
- Conversion: `RH = raw × 100 / 2²⁰`, `T = raw × 200 / 2²⁰ − 50`.

### Accuracy and drift (datasheet)

- **Accuracy:** typically ±0.3 °C and ±2 %RH (25 °C, 20–80 %RH); up to
  ±5–7 %RH at the extremes.
- **Self-heating:** measure no more than once per second. The firmware
  measures every 2 s.
- **Drift:** more than 60 hours above 80 %RH make it read up to +3 %RH high,
  until it slowly recovers in normal air. The firmware counts the time above
  80 %RH ("Time above 80 %RH" in the app, `humid_s` in `/status`). Faster
  recovery (datasheet 4.3): 60–85 °C, below 5 %RH, for 2–10 hours.

## Derived values

From temperature and humidity, both in the firmware and in the app:

| Value | Formula |
|---|---|
| Dew point | Magnus: `γ = ln(RH/100) + 17.62·T/(243.12+T)`, `Td = 243.12·γ / (17.62−γ)` |
| Absolute humidity | `216.7 · RH/100 · 6.112·e^(17.62·T/(243.12+T)) / (273.15+T)` g/m³ |
| Comfort | from the dew point: < 5 °C dry, < 13 pleasant, < 16 humid, < 19 very humid, above that muggy |

## Temperature offset

On this breakout the ENS160's hot plates sit a few millimetres from the AHT21,
so the AHT21 typically reads **1–3 °C above the room**. Neither chip can correct
that: the AHT21's calibration covers its own sensor, and the ENS160 doesn't
report its heat. The firmware adds an **offset** to the temperature, corrects
the humidity to match (below), and feeds the corrected values to the ENS160.

**Setting it by hand:** after 30 minutes, compare with a thermometer you trust
right next to the board and set the difference: in the app (Settings →
Calibration), over MQTT (`/offset -2.0`), or in `config.json`
(`"sensor": {"temperature_offset": -2.0}`).

**Measuring it automatically (ESP32, `firmware/selfcal.py`):** the board
switches the ENS160's heaters off and watches how far its temperature drops.
1. **Warm:** the AHT21's uncorrected temperature, averaged over the last minute.
2. **Cool down:** the ENS160 goes to deep sleep. The firmware waits until the
   temperature changes by less than 0.05 °C in 2 minutes: at least 5 minutes,
   at most `cooldown_min` (20).
3. **Result:** cool minus warm (averaged again) is the offset. It's applied and
   saved, and the ENS160 measures again after its 3-minute warm-up.
4. **Rejected runs:** if the temperature *rose*, the room changed during the
   run, so the result is thrown away ("room temperature changed").

Start it from the app (Calibration → Measure now) or over MQTT
(`/calibrate start`). With "Daily" on (`/calibrate auto on`), it runs every
`calibration_interval_h` hours (24), once the ENS160 has run an hour. While it
runs, the display and the app show "Calibrating", and there are no air
readings. The result depends on airflow: measure again after moving the board
or putting it in a case.

**Humidity follows.** The same amount of water vapour is a higher relative
humidity in cooler air. With the Magnus formula:

```
RH_room = RH_measured × exp(m(T_measured) − m(T_room)),   m(t) = 17.62·t / (243.12 + t)
```

Example: 50 % at 26 °C becomes 56.3 % at 24 °C.

## Averaging

`AirSensor` sums every valid sample between publishes; `take_sums()` hands the
sums over and starts over, and `app.py` turns them into means. That's 60
ENS160 and 30 AHT21 samples per minute.
The display shows the latest values; MQTT gets the averages.

## Changes from the old firmware

The previous code (`esp_manager.py`, `modules/ens160.py`, `modules/aht21.py`)
had these sensor problems:

| Problem | Effect |
|---|---|
| "Soft reset" wrote 0x01 to register 0x11, which is CONFIG, not a reset | turned on the interrupt pin instead |
| Comment said "set IDLE" but wrote 0x02 | it worked by accident (0x02 is the measuring mode) |
| Never wrote TEMP_IN/RH_IN | readings always compensated for 25 °C / 50 % |
| Ignored the validity bits | warm-up values were published as real |
| Read the sensors 20 times in a row and averaged | the ENS160 only updates once a second, so 20 copies of the same value; the AHT21 measured every 80 ms and heated itself |
| No busy/CRC check on the AHT21 | corrupted readings possible |
| Display read the sensors again for every redraw | display and MQTT showed different values, and each read blocked ~2 s |
