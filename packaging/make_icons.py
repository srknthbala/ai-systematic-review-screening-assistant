"""Generate the application icon for both platforms from one definition.

Draws the funnel mark used in the sidebar (many records in, few screened out
the bottom) on a dark rounded square, then writes:

    packaging/icons/icon.icns   macOS bundle icon
    packaging/icons/icon.ico    Windows exe / shortcut icon
    packaging/icons/icon.png    1024px master, for reference

Run:  python packaging/make_icons.py
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "icons"

# Supersample, then downsample, which is cheaper than any manual antialiasing.
SS = 4
SIZE = 1024

BG_TOP = (27, 33, 36)       # --sidebar-2
BG_BOTTOM = (16, 19, 21)
TEAL_LIGHT = (122, 240, 224)
TEAL_DARK = (13, 74, 68)    # a shade under --accent, for a visible falloff
CHECK = (134, 232, 220)

# Funnel outline in the 32x32 space the sidebar SVG uses. All straight lines,
# so it is a plain polygon: M5 7 H27 L19 17 V25 L13 28 V17 Z
FUNNEL = [(5, 7), (27, 7), (19, 17), (19, 25), (13, 28), (13, 17)]
BADGE_C, BADGE_R = (25.6, 25.2), 5.5
CHECK_PTS = [(23.1, 25.3), (24.9, 27.1), (28.2, 23.3)]


def vgradient(size, top, bottom):
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((size, size), Image.BILINEAR)


def dgradient(size, c0, c1):
    """Top-left to bottom-right gradient, built small and scaled up."""
    q = 64
    g = Image.new("RGB", (q, q))
    px = g.load()
    for y in range(q):
        for x in range(q):
            t = (x + y) / (2 * (q - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return g.resize((size, size), Image.BILINEAR)


def build(px):
    """Render the icon at px, using an inset rounded square like macOS wants."""
    n = px * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    # macOS icons sit inside the canvas rather than filling it.
    inset = round(n * 0.094)
    box = (inset, inset, n - inset, n - inset)
    radius = round((box[2] - box[0]) * 0.225)

    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img.paste(vgradient(n, BG_TOP, BG_BOTTOM), (0, 0), mask)

    # Scale the 32-unit artwork into the rounded square, then nudge it up a
    # touch so the funnel reads as optically centred rather than low.
    side = box[2] - box[0]
    art = side * 0.60
    k = art / 32.0
    ox = box[0] + (side - art) / 2
    oy = box[1] + (side - art) / 2 - side * 0.012
    P = lambda x, y: (ox + x * k, oy + y * k)

    funnel_mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(funnel_mask).polygon([P(x, y) for x, y in FUNNEL], fill=255)
    img.paste(dgradient(n, TEAL_LIGHT, TEAL_DARK), (0, 0), funnel_mask)

    d = ImageDraw.Draw(img)
    # Punch the badge out of the funnel so the tick reads cleanly.
    bx, by = P(*BADGE_C)
    br = BADGE_R * k
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=BG_BOTTOM + (255,))
    d.line([P(x, y) for x, y in CHECK_PTS], fill=CHECK + (255,),
           width=max(1, round(2.1 * k)), joint="curve")
    # Round the stroke ends by hand; ImageDraw has no line caps.
    for x, y in (CHECK_PTS[0], CHECK_PTS[2]):
        cx, cy = P(x, y)
        r = max(1, round(2.1 * k)) / 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CHECK + (255,))

    return img.resize((px, px), Image.LANCZOS)



def dmg_background(w=640, h=420):
    """Backdrop for the drag-to-Applications window."""
    img = Image.new("RGB", (w * 2, h * 2), (242, 241, 237))  # @2x for retina
    d = ImageDraw.Draw(img)
    W, H = w * 2, h * 2

    # A soft arrow from the app icon position toward the Applications alias.
    y = int(H * 0.46)
    x0, x1 = int(W * 0.40), int(W * 0.60)
    d.line([(x0, y), (x1 - 26, y)], fill=(160, 168, 162), width=6)
    d.polygon([(x1, y), (x1 - 30, y - 17), (x1 - 30, y + 17)], fill=(160, 168, 162))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    master = build(SIZE)
    master.save(OUT / "icon.png")

    # Windows .ico wants several sizes in one file.
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    build(256).save(OUT / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in ico_sizes])

    # .icns is macOS-only and needs iconutil, so skip the whole iconset dance
    # elsewhere rather than leaving a scratch folder behind on Windows.
    if sys.platform == "darwin":
        iconset = OUT / "icon.iconset"
        if iconset.exists():
            for f in iconset.iterdir():
                f.unlink()
            iconset.rmdir()
        iconset.mkdir()
        try:
            for base in (16, 32, 128, 256, 512):
                build(base).save(iconset / f"icon_{base}x{base}.png")
                build(base * 2).save(iconset / f"icon_{base}x{base}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset),
                            "-o", str(OUT / "icon.icns")], check=True)
        finally:
            for f in iconset.iterdir():
                f.unlink()
            iconset.rmdir()
        print("wrote icon.icns")
    else:
        print("skipped icon.icns (macOS only)")

    print("wrote icon.ico, icon.png")


if __name__ == "__main__":
    main()

