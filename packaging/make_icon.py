"""Writes packaging/icon.png (256x256): a simple original rounded-square icon."""
import os, struct, zlib
S = 256
def px(x, y):
    cx, cy, r = x - S / 2 + .5, y - S / 2 + .5, S / 2 - 8
    # rounded square
    ax, ay = max(abs(cx) - (r - 40), 0), max(abs(cy) - (r - 40), 0)
    if ax * ax + ay * ay > 40 * 40:
        return (0, 0, 0, 0)
    d = (cx * cx + cy * cy) ** .5
    if 52 < d < 78 or (abs(cx) < 12 and cy < -10 and cy > -100):  # ring + stem: a "theme" swirl
        return (255, 255, 255, 255)
    t = (y / S)
    return (int(20 + 30 * t), int(150 + 40 * t), int(220 - 30 * t), 255)
raw = b"".join(b"\0" + b"".join(bytes(px(x, y)) for x in range(S)) for y in range(S))
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png"), "wb").write(png)
