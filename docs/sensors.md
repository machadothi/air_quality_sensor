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
| 0x12 | COMMAND | 0xCC: clear the general-purpose registers |
| 0x13–0x16 | TEMP_IN, RH_IN | compensation: `(T + 273.15) × 64` and `RH × 512`, little-endian |
| 0x20 | DEVICE_STATUS | bit 7 running, bit 6 error, bits 3:2 validity, bit 1 new data |
| 0x21–0x25 | DATA_AQI, DATA_TVOC, DATA_ECO2 | read in one 5-byte burst |

### Start-up sequence (`AirSensor._connect`)

Check PART_ID → reset → idle → clear CONFIG → clear GPR → standard mode. The
reset matters because the old firmware had written to the wrong registers
(see [Changes from the old firmware](#changes-from-the-old-firmware)).

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

## Temperature offset

On this breakout the ENS160's hot plates sit a few millimetres from the AHT21,
so the AHT21 typically reads **1–3 °C above the room**. To correct:
1. Let it run for 30 minutes.
2. Compare with a thermometer you trust.
3. Set the difference in `config.json`, e.g. `"sensor": {"temperature_offset": -2.0}`.

The firmware then also corrects the **humidity**. The same amount of water
vapour is a higher relative humidity in cooler air. With the Magnus formula:

```
RH_room = RH_measured × exp(m(T_measured) − m(T_room)),   m(t) = 17.62·t / (243.12 + t)
```

Example: 50 % at 26 °C becomes 56.3 % at 24 °C. The corrected values are also
what the ENS160 gets as compensation.

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
