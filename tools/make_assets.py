#!/usr/bin/env python3
"""Generate the display fonts and icons: firmware/assets.bin (the bitmaps) and
firmware/assets.py (where each glyph is in the .bin).

Fonts are DejaVu rendered without anti-aliasing at fixed pixel sizes, icons are
drawn as ASCII art below ('#' = lit pixel). Every glyph is stored MONO_HLSB
(rows of bytes, MSB first), the layout gfx.py expects.

The bitmaps live in a file because the ESP8266 has too little RAM to hold them:
gfx.py reads each glyph from flash as it draws it.

Needs Pillow and the DejaVu fonts:
    sudo apt install python3-pil fonts-dejavu-core
Run from the repository root:
    python3 tools/make_assets.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
OUT = Path(__file__).resolve().parent.parent / "firmware" / "assets.py"
OUT_BIN = OUT.with_suffix(".bin")

# name: (ttf file, pixel size, characters, letter spacing)
FONTS = {
    # Big readings. Only what a number needs.
    "BIG": ("DejaVuSans-Bold.ttf", 32, "0123456789.-", 2),
    # Air-quality rating and units.
    "MID": ("DejaVuSans-Bold.ttf", 15, " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.%°-³", 1),
    # Titles and small text.
    "SMALL": ("DejaVuSans-Bold.ttf", 10, " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,:%°-+/()~Ω³·", 1),
}

ICONS = {
    "leaf": """
        ..........##
        .......#####
        .....####.##
        ....###..#.#
        ...###..#..#
        ...##..#..##
        ..##..#...#.
        ..##.#...##.
        ..###...##..
        ...#..###...
        ..#.###.....
        .#..........
    """,
    "cloud": """
        ............
        ............
        ....###.....
        ...#####....
        ..########..
        .##########.
        ############
        ############
        .##########.
        ............
        ............
        ............
    """,
    "flask": """
        ...######...
        ....#..#....
        ....#..#....
        ....#..#....
        ...#....#...
        ..#......#..
        .#........#.
        .##.##.##.#.
        #.########.#
        #.########.#
        .##########.
        ............
    """,
    "thermo": """
        ....##......
        ...#..#.##..
        ...#..#.....
        ...#..#.##..
        ...#..#.....
        ...#.##.##..
        ...#.##.....
        ..#.###.#...
        .#.#####.#..
        .#.#####.#..
        ..#.###.#...
        ...####.....
    """,
    "drop": """
        .....##.....
        .....##.....
        ....####....
        ....####....
        ...######...
        ..########..
        ..########..
        .#.########.
        .#.########.
        .##.#######.
        ..########..
        ....####....
    """,
    "dew": """
        ......#.....
        .....###....
        ....#####...
        ...##.####..
        ...#.#####..
        ...#######..
        ....#####...
        ............
        .#.#.#.#.#..
        ............
        #.#.#.#.#.#.
        ............
    """,
    "chip": """
        ..#.#.#.#...
        .#########..
        ##.......##.
        .#.#####.#..
        ##.#...#.##.
        .#.#.#.#.#..
        ##.#...#.##.
        .#.#####.#..
        ##.......##.
        .#########..
        ..#.#.#.#...
        ............
    """,
    "antenna": """
        .#........#.
        #..#....#..#
        #.#..##..#.#
        #.#.####.#.#
        #..#.##.#..#
        .#...##...#.
        .....##.....
        .....##.....
        ....####....
        ....####....
        ...######...
        ............
    """,
    # Status bar, 8 px high.
    "wifi": """
        ..#######..
        .#.......#.
        #..#####..#
        ..#.....#..
        ....###....
        ...#...#...
        ...........
        .....#.....
    """,
    "wifi_off": """
        #.#####....
        .#.......#.
        #.#####...#
        ..#.#...#..
        ....###....
        ...#..##...
        .........#.
        .....#....#
    """,
    "link": """
        .#.....
        ###....
        .#..#..
        .#..#..
        .#..#..
        ....###
        .....#.
        .......
    """,
}


def pack_hlsb(rows):
    """Rows of 0/1 lists -> bytes, MONO_HLSB."""
    out = bytearray()
    for row in rows:
        for x0 in range(0, len(row), 8):
            byte = 0
            for bit, value in enumerate(row[x0:x0 + 8]):
                if value:
                    byte |= 0x80 >> bit
            out.append(byte)
    return bytes(out)


def render_font(ttf, size, chars, spacing):
    font = ImageFont.truetype(str(FONT_DIR / ttf), size)
    # Common vertical extent over all characters, so all glyphs share a baseline.
    top = min(font.getbbox(c)[1] for c in chars if c != " ")
    bottom = max(font.getbbox(c)[3] for c in chars if c != " ")
    height = bottom - top
    widths, data = [], bytearray()
    for c in chars:
        if c == " ":
            width = max(3, size // 3)
            rows = [[0] * width for _ in range(height)]
        else:
            left, _, right, _ = font.getbbox(c)
            ink = right - left
            image = Image.new("1", (ink, height), 0)
            draw = ImageDraw.Draw(image)
            draw.fontmode = "1"   # no anti-aliasing
            draw.text((-left, -top), c, font=font, fill=1)
            width = ink + spacing
            rows = [[image.getpixel((x, y)) if x < ink else 0 for x in range(width)] for y in range(height)]
        widths.append(width)
        data += pack_hlsb(rows)
    return height, widths, bytes(data)


def parse_icon(art):
    lines = [line.strip() for line in art.strip().splitlines()]
    assert len({len(line) for line in lines}) == 1, "icon rows must have equal length"
    return len(lines[0]), len(lines), pack_hlsb([[c == "#" for c in line] for line in lines])


def main():
    out = [
        "# Display fonts and icons. GENERATED by tools/make_assets.py, don't edit.",
        "# The bitmaps are in assets.bin (MONO_HLSB); this says where.",
        "# Font: (height, chars, widths, offsets as u16 little-endian); icon: (width, height, offset).",
        "",
    ]
    blob = bytearray()
    biggest = 0   # gfx.py reads each glyph into a buffer this big
    for name, (ttf, size, chars, spacing) in FONTS.items():
        height, widths, data = render_font(ttf, size, chars, spacing)
        offsets, offset = bytearray(), len(blob)
        for width in widths:
            offsets += offset.to_bytes(2, "little")
            offset += (width + 7) // 8 * height
            biggest = max(biggest, (width + 7) // 8 * height)
        blob += data
        out.append(f"# {ttf} {size} px, {height} px high, {len(data)} bytes")
        out.append(f"{name} = ({height}, {chars!r},\n    {bytes(widths)!r},\n    {bytes(offsets)!r})")
        out.append("")
    for name, art in ICONS.items():
        width, height, data = parse_icon(art)
        out.append(f"ICON_{name.upper()} = ({width}, {height}, {len(blob)})")
        blob += data
        biggest = max(biggest, len(data))
    out.append("")
    out.append(f"MAX_GLYPH_BYTES = {biggest}")
    OUT.write_text("\n".join(out) + "\n")
    OUT_BIN.write_bytes(blob)
    print(f"wrote {OUT} and {OUT_BIN} ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
