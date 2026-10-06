# Hardware

| Part | I2C address | Notes |
|---|---|---|
| ESP8266 board (NodeMCU / Wemos D1 mini style) | | 80/160 MHz, 4 MB flash, ~36 KB RAM free for MicroPython, Wi-Fi 2.4 GHz |
| ENS160 + AHT21 breakout | 0x53 (ENS160), 0x38 (AHT21) | the common purple "ENS160 AHT21" module, 3.3 V |
| SSD1306 OLED 0.96", 128×64, I2C, 4 pins | 0x3C | optional; some modules use 0x3D (`display.address`) |

## Wiring

All three parts share one I2C bus. Both modules have pull-up resistors on board.

| Signal | ESP8266 GPIO | NodeMCU / Wemos label | ENS160 module | OLED |
|---|---|---|---|---|
| SCL | GPIO5 | D1 | SCL | SCL |
| SDA | GPIO4 | D2 | SDA | SDA |
| 3.3 V | 3V3 | 3V3 | VIN | VCC |
| GND | GND | G | GND | GND |

```
 ESP8266            ENS160+AHT21        SSD1306
 D1 (GPIO5) ──┬──── SCL           ┌──── SCL
              └───────────────────┘
 D2 (GPIO4) ──┬──── SDA           ┌──── SDA
              └───────────────────┘
 3V3 ─────────┬──── VIN           ┌──── VCC
              └───────────────────┘
 GND ─────────┬──── GND           ┌──── GND
              └───────────────────┘
```

Check the wiring from the PC; it should list 56 (0x38), 60 (0x3C) and 83 (0x53):

```sh
.venv/bin/mpremote connect /dev/ttyUSB0 exec "from machine import SoftI2C, Pin; print(SoftI2C(scl=Pin(5), sda=Pin(4)).scan())"
```

## ESP32

The firmware also runs on an ESP32: set `"esp": "esp32"` in `config.json`
(default pins SCL 22, SDA 21). The ESP32's MicroPython build doesn't include
the SSD1306 driver, so install it once with
`.venv/bin/mpremote mip install ssd1306`.

## Placement

- **Not in a closed box.** The sensors need moving air; a few holes are not enough.
- **Away from the ESP8266 and its regulator,** which get warm. The ENS160's heater
  also warms the AHT21 next to it; see
  [sensors.md](sensors.md#temperature-offset) for the correction.
- **USB power** from a phone charger is fine: the ENS160 draws ~30 mA, the ESP8266 70–200 mA.
