"""Stand-in for MicroPython's machine module on the PC (tools/preview.py):
just enough for ui.py (display reset pin) and sensors.py to import."""


class Pin:
    OUT = 1
    IN = 0

    def __init__(self, pin, mode=IN, value=None):
        self.pin, self.state = pin, value or 0

    def __call__(self, value=None):
        if value is not None:
            self.state = value
        return self.state


class RTC:
    def memory(self, data=None):
        return b""
