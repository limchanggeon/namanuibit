"""Generate the app icon set (icon.png, icon.icns, icon.ico) from code."""

from pathlib import Path
import subprocess
import shutil
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
S = 1024
BG_TOP, BG_BOTTOM = (43, 46, 49), (20, 22, 24)
ACCENT = (214, 184, 139)


def master() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gradient = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        gradient.putpixel(
            (0, y), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
        )
    gradient = gradient.resize((S, S))

    # macOS-style rounded square, inset from the canvas edge.
    inset, radius = round(S * 0.08), round(S * 0.225)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, S - inset, S - inset), radius=radius, fill=255
    )
    im.paste(gradient, (0, 0), mask)

    # A soft warm glow behind the mark, so it reads as light in a dark room.
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (round(S * 0.14), round(S * 0.02), round(S * 0.86), round(S * 0.62)),
        fill=(255, 226, 180, 34),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.09))
    glow.putalpha(Image.composite(glow.getchannel("A"), Image.new("L", (S, S)), mask))
    im = Image.alpha_composite(im, glow)

    # The ◩ brand mark: a square with its left half filled.
    d = ImageDraw.Draw(im)
    m, stroke = round(S * 0.325), round(S * 0.042)
    box = (m, m, S - m, S - m)
    d.rectangle((box[0], box[1], (box[0] + box[2]) // 2, box[3]), fill=ACCENT)
    d.rectangle(box, outline=ACCENT, width=stroke)

    # A hairline rim keeps the tile from melting into a dark dock.
    ImageDraw.Draw(im).rounded_rectangle(
        (inset, inset, S - inset, S - inset),
        radius=radius,
        outline=(255, 255, 255, 20),
        width=round(S * 0.004),
    )
    return im


def main() -> int:
    icon = master()
    icon.save(HERE / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(HERE.parent / "static" / "icon.png")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    icon.save(HERE / "icon.ico", sizes=[(s, s) for s in sizes])

    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = HERE / "icon.iconset"
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(
                iconset / f"icon_{size}x{size}.png"
            )
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(
                iconset / f"icon_{size}x{size}@2x.png"
            )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")],
            check=True,
        )
        shutil.rmtree(iconset)
    print("icons written to", HERE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
