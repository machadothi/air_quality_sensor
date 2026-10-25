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
        if self.fmt == MONO_VLSB and self.height % 8 == 0:   # fast path: whole bytes
            self.buf[:] = bytes([0xFF if c else 0]) * len(self.buf)
            return
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
        if (key == -1 and palette is None and self.fmt == src.fmt == MONO_VLSB and y % 8 == 0 and src.height % 8 == 0
                and 0 <= x and x + src.width <= self.width and 0 <= y and y + src.height <= self.height):
            for page in range(src.height // 8):   # fast path: copy whole byte columns
                d = (y // 8 + page) * self.width + x
                self.buf[d:d + src.width] = src.buf[page * src.width:(page + 1) * src.width]
            return
        for sy in range(src.height):
            for sx in range(src.width):
                c = src.pixel(sx, sy)
                if palette is not None:
                    c = palette.pixel(c, 0)
                if c != key:
                    self.pixel(x + sx, y + sy, c)

    def scroll(self, dx, dy):
        if self.fmt == MONO_VLSB and dy == 0 and self.height % 8 == 0 and abs(dx) < self.width:
            w = self.width   # fast path: shift each byte row; uncovered pixels stay, as on the board
            for page in range(self.height // 8):
                row = self.buf[page * w:(page + 1) * w]
                if dx > 0:
                    row[dx:] = row[:w - dx]
                elif dx < 0:
                    row[:w + dx] = row[-dx:]
                self.buf[page * w:(page + 1) * w] = row
            return
        old = [[self.pixel(x, y) for x in range(self.width)] for y in range(self.height)]
        for y in range(self.height):
            for x in range(self.width):
                sx, sy = x - dx, y - dy
                if 0 <= sx < self.width and 0 <= sy < self.height:
                    self.pixel(x, y, old[sy][sx])
