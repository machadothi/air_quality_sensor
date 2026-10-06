# Hardware

The firmware runs on an **ESP32** (Wi-Fi + Bluetooth) or an **ESP8266**
(Wi-Fi only). It detects which one it's on; the same code and `config.json`
work on both.

| Part | I2C address | Notes |
|---|---|---|
| **ESP32** dev board (ESP32-D0WD, e.g. DevKit V1 with CP2102 USB) | | 240 MHz dual core, 4 MB flash, ~165 KB RAM free for MicroPython, Wi-Fi + Bluetooth LE |
| or ESP8266 board (NodeMCU / Wemos D1 mini) | | 4 MB flash, ~36 KB RAM free, Wi-Fi only |
| ENS160 + AHT21 breakout | 0x53 (ENS160), 0x38 (AHT21) | the common purple "ENS160 AHT21" module |
| OLED 128×64: 2.42" SSD1309 (7 pins) or 0.96" SSD1306 (4 pins) | 0x3C | optional |

## Wiring: ESP32

All parts share one I2C bus on GPIO21/GPIO22. These pins don't affect how the
ESP32 boots; GPIO0, 2, 5, 12 and 15 would, so keep the I2C pull-ups off those.

| Signal | ESP32 pin | ENS160 + AHT21 | 2.42" OLED (7 pins) | 0.96" OLED (4 pins) |
|---|---|---|---|---|
| SDA | GPIO21 (D21) | SDA | SDA (D1) | SDA |
| SCL | GPIO22 (D22) | SCL | SCK (D0) | SCL |
| reset | GPIO4 (D4) | – | RES | – |
| 3.3 V | 3V3 | VIN | – | VCC |
| 5 V | VIN / 5V | – | VCC | – |
| GND | GND | GND | GND, **DC**, **CS** | GND |

The 2.42" module needs some care:
- **I2C mode.** The 7-pin module ships in SPI mode; a resistor on its back
  selects I2C. DC to GND sets address 0x3C, and CS goes to GND.
- **Reset pulse.** It starts only after a pulse on RES. The firmware sends one
  on GPIO4 at start-up (`pins.display_reset`).
- **Power it from 5 V.** The panel draws more than the small ones. Its own
  regulator turns 5 V into 3.3 V, which keeps that load off the ESP32's 3.3 V
  regulator: on 3V3 it kept the ESP32 from booting. Check first that SDA/SCL
  on the module measure ~3.3 V, not 5 V, against GND (with only VCC and GND
  connected); the ESP32's pins are not 5 V tolerant.

## Wiring: ESP8266

| Signal | ESP8266 GPIO | NodeMCU label | ENS160 module | OLED (4 pins) |
|---|---|---|---|---|
| SCL | GPIO5 | D1 | SCL | SCL |
| SDA | GPIO4 | D2 | SDA | SDA |
| 3.3 V | 3V3 | 3V3 | VIN | VCC |
| GND | GND | G | GND | GND |

## Checking the wiring

The scan should list 56 (0x38), 60 (0x3C) and 83 (0x53):

```sh
# ESP32 (the 2.42" display answers only after its reset pulse on GPIO4)
.venv/bin/mpremote connect /dev/ttyUSB0 exec "from machine import SoftI2C, Pin; import time; r=Pin(4,Pin.OUT); r(0); time.sleep_ms(10); r(1); time.sleep_ms(10); print(SoftI2C(scl=Pin(22), sda=Pin(21)).scan())"
# ESP8266
.venv/bin/mpremote connect /dev/ttyUSB0 exec "from machine import SoftI2C, Pin; print(SoftI2C(scl=Pin(5), sda=Pin(4)).scan())"
```

Pins can be changed in `config.json`:
`"pins": {"esp32": {"i2c_scl": 22, "i2c_sda": 21, "display_reset": 4}}`.

## Placement

- **Not in a closed box.** The sensors need moving air; a few holes are not enough.
- **Away from the board's chip and regulator,** which get warm. The ENS160's
  heater also warms the AHT21 next to it; see
  [sensors.md](sensors.md#temperature-offset) for the correction.
- **USB power** from a phone charger is fine: the ENS160 draws ~30 mA, the
  ESP32 up to ~250 mA with Wi-Fi and Bluetooth, the 2.42" OLED up to ~80 mA.
