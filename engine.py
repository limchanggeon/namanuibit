"""Float32 photo adjustments. Independent approximations, not Adobe's process engine."""

import colorsys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, minimum_filter
from adjustments import COLORS

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def luminance(a):
    return np.sum(a * LUMA, axis=-1)


def blur(a, sigma):
    return gaussian_filter(
        a, (sigma, sigma, 0) if a.ndim == 3 else sigma, mode="reflect"
    )


def smoothstep(lo, hi, x):
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def rgb_hsl(a):
    a = a.clip(0, 1)
    high = a.max(axis=-1)
    low = a.min(axis=-1)
    delta = high - low
    light = (high + low) * 0.5
    sat = np.divide(
        delta, 1 - np.abs(2 * light - 1), out=np.zeros_like(light), where=(delta > 1e-7)
    )
    d = np.maximum(delta, 1e-7)
    h = (
        np.where(
            high == a[..., 0],
            ((a[..., 1] - a[..., 2]) / d) % 6,
            np.where(
                high == a[..., 1],
                (a[..., 2] - a[..., 0]) / d + 2,
                (a[..., 0] - a[..., 1]) / d + 4,
            ),
        )
        / 6
    )
    h = np.where(delta > 1e-7, h, 0)
    return h, sat, light


def hsl_rgb(h, s, l):
    c = (1 - np.abs(2 * l - 1)) * s
    hp = (h % 1) * 6
    x = c * (1 - np.abs(hp % 2 - 1))
    z = np.zeros_like(c)
    sector = np.floor(hp).astype(np.int8)
    r = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [c, x, z, z, x],
        default=c,
    )
    g = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [x, c, c, x, z],
        default=z,
    )
    b = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [z, z, x, c, c],
        default=x,
    )
    return np.stack([r, g, b], axis=-1) + (l - c * 0.5)[..., None]


def mix_hsl(a, s):
    if not any(
        getattr(s, f"{k}_{c}") for c, _, _ in COLORS for k in ("hue", "sat", "lum")
    ):
        return a
    h, sat, l = rgb_hsl(a)
    dh = np.zeros_like(h)
    ds = dh.copy()
    dl = dh.copy()
    degrees = h * 360
    # Piecewise hue tents interpolate neighboring color bands without gaps or doubling.
    centers = [c[2] for c in COLORS]
    for i, (color, _, center) in enumerate(COLORS):
        left = (center - centers[i - 1]) % 360
        right = (centers[(i + 1) % 8] - center) % 360
        dist = (degrees - center + 180) % 360 - 180
        weight = np.where(
            dist < 0, np.maximum(0, 1 + dist / left), np.maximum(0, 1 - dist / right)
        )
        dh += weight * getattr(s, f"hue_{color}") / 100 / 12
        ds += weight * getattr(s, f"sat_{color}") / 100
        dl += weight * getattr(s, f"lum_{color}") / 100
    h = (h + dh) % 1
    sat = np.clip(sat * (1 + ds), 0, 1)
    l = np.clip(l + dl * 0.4 * (1 - np.abs(2 * l - 1)), 0, 1)
    return hsl_rgb(h, sat, l)


def calibration(a, s):
    # Primary chroma vectors mix RGB channels; this is a display-referred calibration.
    if any(
        getattr(s, f"calibration_{c}_{k}")
        for c in ("red", "green", "blue")
        for k in ("hue", "sat")
    ):
        matrix = np.eye(3, dtype=np.float32)
        for i, c in enumerate(("red", "green", "blue")):
            hue = getattr(s, f"calibration_{c}_hue") / 100 * 0.25
            sat = getattr(s, f"calibration_{c}_sat") / 100 * 0.35
            matrix[i, (i + 1) % 3] += hue
            matrix[i, (i + 2) % 3] -= hue
            matrix[i, i] += sat
            matrix[i, (i + 1) % 3] -= sat / 2
            matrix[i, (i + 2) % 3] -= sat / 2
        a = a @ matrix
    if s.shadow_tint:
        mask = (1 - luminance(a).clip(0, 1)) ** 3 * s.shadow_tint / 100 * 0.08
        a = a + mask[..., None] * np.array([0.5, -1, 0.5], dtype=np.float32)
    return a


def tone_curves(a, s):
    if any(
        getattr(s, "parametric_" + k)
        for k in ("shadows", "darks", "lights", "highlights")
    ):
        l = luminance(a).clip(0, 1)
        b1, b2, b3 = (
            s.shadow_split / 100,
            s.midtone_split / 100,
            s.highlight_split / 100,
        )
        centers = [b1 / 2, (b1 + b2) / 2, (b2 + b3) / 2, (b3 + 1) / 2]
        delta = np.zeros_like(l)
        for i, k in enumerate(("shadows", "darks", "lights", "highlights")):
            nodes = [0, *centers, 1]
            weights = [0, 0, 0, 0, 0, 0]
            weights[i + 1] = getattr(s, "parametric_" + k) / 100 * 0.22
            delta += np.interp(l, nodes, weights).astype(np.float32)
        a = a + delta[..., None]
    original_saturation = rgb_hsl(a)[1] if s.curve_saturation != 100 else None
    for channel, name in [(None, "rgb"), (0, "red"), (1, "green"), (2, "blue")]:
        pts = getattr(s, "curve_" + name)
        if pts[0][0] == 0 and pts[-1][0] == 255 and all(x == y for x, y in pts):
            continue
        points = np.array(pts, dtype=np.float32) / 255
        if channel is None:
            a = np.interp(a, points[:, 0], points[:, 1]).astype(np.float32)
        else:
            a[..., channel] = np.interp(a[..., channel], points[:, 0], points[:, 1])
    if original_saturation is not None:
        hue, saturation, light = rgb_hsl(a)
        a = hsl_rgb(
            hue,
            original_saturation
            + (saturation - original_saturation) * s.curve_saturation / 100,
            light,
        )
    return a


def grade(a, s):
    if not any(
        getattr(s, f"grade_{zone}_{k}")
        for zone in ("shadow", "midtone", "highlight", "global")
        for k in ("sat", "lum")
    ):
        return a
    l = luminance(a).clip(0, 1)
    center = 0.5 - s.grade_balance * 0.003
    width = 0.12 + s.grade_blending * 0.0038
    shadows = 1 - smoothstep(center - width, center + width, l)
    highs = smoothstep(center - width, center + width, l)
    middle = np.maximum(0, 1 - np.abs(l - center) / (0.25 + width))
    weights = [shadows, middle, highs]
    denom = shadows + middle + highs
    for zone, weight in zip(
        ("shadow", "midtone", "highlight", "global"),
        [*(w / denom for w in weights), np.ones_like(l)],
    ):
        hue = getattr(s, f"grade_{zone}_hue") / 360
        strength = getattr(s, f"grade_{zone}_sat") / 100 * 0.3
        tint = np.array(colorsys.hsv_to_rgb(hue, 1, 1), dtype=np.float32)
        tint -= np.dot(tint, LUMA)
        a += (
            weight[..., None]
            * tint
            * strength
            * (0.25 + 0.75 * (1 - np.abs(2 * l - 1)))[..., None]
        )
        a += weight[..., None] * getattr(s, f"grade_{zone}_lum") / 100 * 0.25
    return a


def denoise(a, s, scale):
    if not (s.noise_luminance or s.noise_color):
        return a
    l = luminance(a)
    smoothed = blur(l, max(0.4, scale * (0.6 + s.noise_luminance / 45)))
    edge = np.abs(l - blur(l, max(0.4, scale)))
    if s.noise_color:
        chroma = a - l[..., None]
        reduced = blur(chroma, max(0.4, scale * (0.5 + s.noise_color_smooth / 25)))
        gate = np.exp(-edge * (5 + s.noise_color_detail * 0.5))
        chroma += (reduced - chroma) * (s.noise_color / 100) * gate[..., None]
    else:
        chroma = a - l[..., None]
    if s.noise_luminance:
        gate = np.exp(-edge * (5 + s.noise_detail * 0.8 + s.noise_contrast * 0.8))
        l = l + (smoothed - l) * s.noise_luminance / 100 * gate
    return l[..., None] + chroma


def atmosphere(a, s, scale):
    if not s.dehaze:
        return a
    if s.dehaze < 0:
        return a * (1 + s.dehaze / 200) - s.dehaze / 200 * 0.85
    # Dark-channel transmission estimate with a bounded airlight estimate.
    channel = a.min(axis=-1).clip(0, 1)
    dark = minimum_filter(channel, size=max(3, int(12 * scale) | 1), mode="reflect")
    air = max(0.5, float(np.percentile(a[::8, ::8], 99)))
    transmission = np.maximum(
        0.22, 1 - s.dehaze / 100 * 0.9 * blur(dark, max(0.5, scale * 5)) / air
    )
    return (a - air) / transmission[..., None] + air


def local_detail(a, s, scale):
    l = luminance(a)
    if s.texture:
        fine = blur(l, max(0.3, scale * 0.5)) - blur(l, max(0.6, scale * 2))
        a += fine[..., None] * s.texture / 100
    if s.clarity:
        coarse = l - blur(l, max(0.5, scale * 10))
        a += coarse[..., None] * s.clarity / 100 * 0.7
    if s.sharpness:
        l = luminance(a)
        detail = l - blur(l, max(0.25, s.sharpen_radius * scale))
        edge = np.abs(l - blur(l, max(0.5, scale * 2)))
        threshold = s.sharpen_masking / 100 * 0.12
        mask = (
            smoothstep(threshold, threshold + 0.025, edge) if s.sharpen_masking else 1
        )
        fine = l - blur(l, max(0.25, scale * 0.5))
        sharpen = detail * (1 - s.sharpen_detail / 200) + fine * s.sharpen_detail / 100
        a += (
            sharpen[..., None] * (s.sharpness / 100 * 1.8) * np.asarray(mask)[..., None]
        )
    return a


def defringe(a, s, scale):
    if not (s.defringe_purple or s.defringe_green):
        return a
    h, sat, l = rgb_hsl(a)
    degrees = h * 360
    edge = np.abs(l - blur(l, max(0.5, scale * 1.5)))
    edge_gate = smoothstep(0.015, 0.12, edge)
    for color, start, span in [("purple", 210, 150), ("green", 40, 150)]:
        amount = getattr(s, "defringe_" + color)
        lo = start + getattr(s, f"defringe_{color}_lo") / 100 * span
        hi = start + getattr(s, f"defringe_{color}_hi") / 100 * span
        mask = smoothstep(lo - 8, lo, degrees) * (1 - smoothstep(hi, hi + 8, degrees))
        sat *= 1 - mask * edge_gate * amount / 20
    return hsl_rgb(h, sat, l)


def finish(a, s):
    h, w = a.shape[:2]
    if s.vignette:
        y, x = np.ogrid[-1 : 1 : complex(h), -1 : 1 : complex(w)]
        p = 2 + (max(0, -s.vignette_roundness) / 100) * 6
        radius = ((np.abs(x) ** p + np.abs(y) ** p) / 2) ** (1 / p)
        if s.vignette_roundness > 0:
            radius = np.sqrt((x * w / max(h, w)) ** 2 + (y * h / max(h, w)) ** 2)
        midpoint = s.vignette_midpoint / 100 * 0.8
        mask = smoothstep(
            midpoint, min(1.5, midpoint + 0.05 + s.vignette_feather / 100), radius
        )
        light = luminance(a).clip(0, 1)
        if s.vignette < 0 and s.vignette_style != 2:
            mask *= 1 - s.vignette_highlights / 100 * light**3
        amount = mask[..., None] * abs(s.vignette) / 100 * 0.85
        if s.vignette_style == 2:
            a = a * (1 - amount) + (amount if s.vignette > 0 else 0)
        elif s.vignette_style == 1:
            a = a * (1 + amount * np.sign(s.vignette))
        else:
            # Protect bright areas more strongly in highlight-priority mode.
            a = a + np.sign(s.vignette) * amount * (1 - light[..., None] ** 2) * 0.6

    if s.grain:
        # Fixed spatial field keeps previews, undo and repeated exports deterministic.
        rng = np.random.default_rng(1729)
        field = rng.standard_normal((512, 512)).astype(np.float32)
        field = blur(field, 0.2 + s.grain_size / 100 * 2)
        field /= max(float(field.std()), 1e-5)
        fine = rng.standard_normal((512, 512)).astype(np.float32)
        field = field * (1 - s.grain_roughness / 200) + fine * s.grain_roughness / 200
        noise = np.asarray(
            Image.fromarray(field).resize((w, h), Image.Resampling.BILINEAR)
        )
        a = (
            a
            + noise[..., None]
            * s.grain
            / 100
            * 0.075
            * (0.3 + 0.7 * (1 - np.abs(2 * luminance(a).clip(0, 1) - 1)))[..., None]
        )
    return a.clip(0, 1)


def process(base, s):
    a = np.array(base, dtype=np.float32, copy=True)
    scale = max(0.5, max(a.shape[:2]) / 1600)
    a = denoise(a, s, scale)
    a = np.where(a <= 0.04045, a / 12.92, (np.maximum(a + 0.055, 0) / 1.055) ** 2.4)
    a *= 2**s.exposure
    a = np.where(
        a <= 0.0031308, a * 12.92, 1.055 * np.maximum(a, 0) ** (1 / 2.4) - 0.055
    )
    a *= np.array(
        [1 + s.temperature * 0.002, 1 - s.tint * 0.0015, 1 - s.temperature * 0.002],
        dtype=np.float32,
    )
    a = calibration(a, s)
    l = luminance(a)[..., None].clip(0, 1)
    a += s.shadows / 100 * 0.3 * (1 - l) ** 2 + s.highlights / 100 * 0.3 * l**2
    a += s.whites / 100 * 0.2 * l**4 + s.blacks / 100 * 0.2 * (1 - l) ** 4
    a = (a - 0.5) * (1 + s.contrast / 150) + 0.5
    a = atmosphere(a, s, scale)
    a = tone_curves(a, s)
    a = mix_hsl(a, s)
    gray = luminance(a)[..., None]
    sat = a.max(axis=-1, keepdims=True) - a.min(axis=-1, keepdims=True)
    a = gray + (a - gray) * (1 + s.saturation / 100) * (
        1 + s.vibrance / 100 * (1 - sat.clip(0, 1))
    )
    if s.monochrome:
        a = np.repeat(gray, 3, axis=-1)
    a = grade(a, s)
    a = local_detail(a, s, scale)
    a = defringe(a, s, scale)
    # Geometry precedes post-crop vignette and grain.
    if s.rotation:
        a = np.rot90(a, -s.rotation).copy()
    if s.crop != "original":
        rw, rh = map(int, s.crop.split(":"))
        ratio = rw / rh
        h, w = a.shape[:2]
        nw, nh = (
            (max(1, int(h * ratio)), h)
            if w / h > ratio
            else (w, max(1, int(w / ratio)))
        )
        x, y = (w - nw) // 2, (h - nh) // 2
        a = a[y : y + nh, x : x + nw]
    return Image.fromarray(np.uint8(np.round(finish(a, s) * 255)))
