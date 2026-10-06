"""Stand-in for MicroPython's ssd1306 driver: a frame buffer whose show()
hands each frame to on_show (tools/preview.py saves them as images)."""

import framebuf

on_show = None


class SSD1306_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        super().__init__(bytearray(width * height // 8), width, height, framebuf.MONO_VLSB)

    def contrast(self, value):
        pass

    def rotate(self, rotate):
        pass

    def poweroff(self):
        pass

    def show(self):
        if on_show:
            on_show(self)
