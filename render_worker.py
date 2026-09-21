"""Decoding, developing and encoding — the slow half of the app.

These run in a child process. On Windows the WebView2 message loop is driven
from the UI process's Python thread, so a long render there starves the GIL for
seconds at a time and Windows paints the window as "not responding" — including
any loading indicator the page is trying to animate. Keeping the work in
another process leaves the UI process free to repaint.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageOps

from engine import process
from settings import Settings

RAW = {
    ".cr2",
    ".cr3",
    ".nef",
    ".nrw",
    ".arw",
    ".dng",
    ".raf",
    ".orf",
    ".rw2",
    ".pef",
    ".srw",
    ".raw",
}
RASTER = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
SUPPORTED = RAW | RASTER
# Pillow refuses WebP beyond this, and a silent failure at the end of a long
# export is worse than saying so up front.
WEBP_MAX_EDGE = 16383


def decode(path):
    if Path(path).suffix.lower() in RAW:
        with rawpy.imread(str(path)) as raw:
            return (
                raw.postprocess(
                    use_camera_wb=True, no_auto_bright=True, output_bps=16
                ).astype(np.float32)
                / 65535
            )
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source)
        if source.info.get("icc_profile"):
            im = ImageCms.profileToProfile(
                im,
                ImageCms.ImageCmsProfile(BytesIO(source.info["icc_profile"])),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        return np.asarray(im.convert("RGB"), dtype=np.float32) / 255


def encode(im, fmt="jpeg", quality=92):
    if fmt == "webp" and max(im.size) > WEBP_MAX_EDGE:
        raise ValueError(
            f"WebP는 긴 변 {WEBP_MAX_EDGE:,}px까지만 저장할 수 있습니다. "
            "이미지 크기를 줄여 내보내세요."
        )
    out = BytesIO()
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    im.save(out, format=fmt.upper(), quality=quality, icc_profile=icc)
    return out.getvalue()


def render(base, s):
    return process(base, s)


def develop(source, settings, fmt="jpeg", quality=95, long_edge=0, dest=None):
    """Full-size render of one photo. Runs in the pool, so arguments are plain.

    Returns the encoded bytes, or the destination path when it wrote the file
    itself — sending megabytes back through the pool for nothing is wasteful.
    """
    s = settings if isinstance(settings, Settings) else Settings(**settings)
    im = render(decode(Path(source)), s)
    if long_edge:
        im.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    data = encode(im, fmt, quality)
    if dest is None:
        return data
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target)


def preview(path, settings):
    """Render the stored proxy. Cheap enough to stay in the calling process."""
    s = settings if isinstance(settings, Settings) else Settings(**settings)
    with Image.open(path) as im:
        a = np.asarray(im, dtype=np.float32) / 255
    return encode(render(a, s))
