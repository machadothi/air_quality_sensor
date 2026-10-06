"""Just enough of MicroPython's framebuf, in plain Python, to preview the
screens on a PC (tools/preview.py). Only the 1-bit formats are supported."""

MONO_VLSB = 0
MONO_HLSB = 3


class FrameBuffer:
    def __init__(self, buf, width, height, fmt):
        self.buf, self.width, self.height, self.fmt = buf, width, height, fmt
        self.stride = (width + 7) // 8

    def _index(self, x, y):
        if self.fmt == MONO_VLSB:
            return (y >> 3) * self.width + x, 1 << (y & 7)
        return y * self.stride + (x >> 3), 0x80 >> (x & 7)

    def pixel(self, x, y, c=None):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None if c is None else None
        i, bit = self._index(x, y)
        if c is None:
            return 1 if self.buf[i] & bit else 0
        if c:
            self.buf[i] |= bit
        else:
            self.buf[i] &= ~bit & 0xFF

    def fill(self, c):
        for y in range(self.height):
            for x in range(self.width):
                self.pixel(x, y, c)

    def fill_rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.pixel(xx, yy, c)

    def hline(self, x, y, w, c):
        self.fill_rect(x, y, w, 1, c)

    def vline(self, x, y, h, c):
        self.fill_rect(x, y, 1, h, c)

    def rect(self, x, y, w, h, c, f=False):
        if f:
            return self.fill_rect(x, y, w, h, c)
        self.hline(x, y, w, c)
        self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c)
        self.vline(x + w - 1, y, h, c)

    def line(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.pixel(x0, y0, c)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def blit(self, src, x, y, key=-1, palette=None):
        for sy in range(src.height):
            for sx in range(src.width):
                c = src.pixel(sx, sy)
                if palette is not None:
                    c = palette.pixel(c, 0)
                if c != key:
                    self.pixel(x + sx, y + sy, c)

    def scroll(self, dx, dy):
        old = [[self.pixel(x, y) for x in range(self.width)] for y in range(self.height)]
        for y in range(self.height):
            for x in range(self.width):
                sx, sy = x - dx, y - dy
                if 0 <= sx < self.width and 0 <= sy < self.height:
                    self.pixel(x, y, old[sy][sx])
