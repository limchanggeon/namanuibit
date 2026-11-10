"""Conservative line-based alignment and a shared preview/export geometry map."""
import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d, sobel, map_coordinates, maximum_filter, rotate
from scipy.optimize import least_squares


def matrix(angle=0, vertical=0, horizontal=0):
    t = np.radians(angle)
    c, sn = np.cos(t), np.sin(t)
    return np.array([[c, -sn, 0], [sn, c, 0],
                     [horizontal / 200, vertical / 200, 1]], dtype=float)


def warp(a, angle=0, vertical=0, horizontal=0, distortion=0):
    """One inverse resampling; trim to a valid centred rectangle of the same ratio.

    Coordinates use half the diagonal, so radial strength is resolution invariant.
    Positive distortion samples farther from the centre.
    """
    if not any((angle, vertical, horizontal, distortion)):
        return a
    h, w = a.shape[:2]
    radius = np.hypot(w - 1, h - 1) / 2 or 1
    hx, hy = (w - 1) / (2 * radius), (h - 1) / (2 * radius)
    inv = np.linalg.inv(matrix(angle, vertical, horizontal))
    k = distortion / 300

    def source(x, y):
        z = inv[2, 0] * x + inv[2, 1] * y + inv[2, 2]
        u = (inv[0, 0] * x + inv[0, 1] * y) / z
        v = (inv[1, 0] * x + inv[1, 1] * y) / z
        radial = 1 + k * (u * u + v * v)
        return u * radial, v * radial

    # Include the interior: pincushion maps can have extrema away from corners.
    yy, xx = np.meshgrid(np.linspace(-hy, hy, 81), np.linspace(-hx, hx, 81), indexing="ij")
    lo, hi = 0., 1.
    for _ in range(22):
        mid = (lo + hi) / 2
        u, v = source(xx * mid, yy * mid)
        if np.all(np.abs(u) <= hx) and np.all(np.abs(v) <= hy):
            lo = mid
        else:
            hi = mid
    nw, nh = max(1, int(w * lo)), max(1, int(h * lo))
    out = np.empty((nh, nw, a.shape[2]), dtype=a.dtype)
    # Chunk coordinates to avoid several full-resolution float64 image grids.
    x = (np.arange(nw, dtype=np.float32) - (nw - 1) / 2) / radius
    for row in range(0, nh, 128):
        y = (np.arange(row, min(row + 128, nh), dtype=np.float32) - (nh - 1) / 2) / radius
        u, v = source(x[None, :], y[:, None])
        coords = [v * radius + (h - 1) / 2, u * radius + (w - 1) / 2]
        for ch in range(a.shape[2]):
            out[row:row + len(y), :, ch] = map_coordinates(
                a[..., ch], coords, order=1, mode="nearest", prefilter=False)
    return out


def lines(a):
    """Long coherent edges, with orientation voting and fitted subpixel endpoints."""
    g = gaussian_filter(a @ np.array([.2126, .7152, .0722]), 1)
    gx, gy = sobel(g, axis=1), sobel(g, axis=0)
    mag = np.hypot(gx, gy)
    if mag.max() < .02:
        return []
    # Keep local ridges along the dominant gradient axis, not whole edge bands.
    ridge = np.where(np.abs(gx) > np.abs(gy),
                     mag >= maximum_filter(mag, size=(1, 3)),
                     mag >= maximum_filter(mag, size=(3, 1)))
    mask = ridge & (mag > max(.02, np.percentile(mag, 88)))
    mask[:5] = mask[-5:] = False
    mask[:, :5] = mask[:, -5:] = False
    yy, xx = np.nonzero(mask)
    if len(xx) < 30:
        return []
    strength = mag[yy, xx]
    direction = np.degrees(np.arctan2(gy[yy, xx], gx[yy, xx])) % 180
    diagonal = int(np.hypot(*g.shape)) + 2
    result = []
    for family, centre in (("v", 0), ("h", 90)):
        angles = np.arange(centre - 22, centre + 22.01, .25)
        votes = np.zeros((len(angles), 2 * diagonal + 1))
        for i, angle in enumerate(angles):
            close = np.abs((direction - angle + 90) % 180 - 90) < 4
            t = np.radians(angle)
            rho = np.rint(xx[close] * np.cos(t) + yy[close] * np.sin(t)).astype(int) + diagonal
            votes[i] = np.bincount(rho, weights=strength[close], minlength=votes.shape[1])
        for _ in range(32):
            i, j = np.unravel_index(votes.argmax(), votes.shape)
            if votes[i, j] < max(g.shape) * .025:
                break
            t = np.radians(angles[i])
            distance = xx * np.cos(t) + yy * np.sin(t) - (j - diagonal)
            near = np.abs(distance) < 2.5
            near &= np.abs((direction - angles[i] + 90) % 180 - 90) < 5
            votes[max(0, i - 5):i + 6, max(0, j - 7):j + 8] = 0
            points = np.column_stack([xx[near], yy[near]]).astype(float)
            if len(points) < 25:
                continue
            along = points @ np.array([-np.sin(t), np.cos(t)])
            order = np.argsort(along)
            chunks = np.split(order, np.flatnonzero(np.diff(along[order]) > 8) + 1)
            chunk = max(chunks, key=len)
            points = points[chunk]
            if len(points) < 25:
                continue
            mean = points.mean(axis=0)
            _, _, vt = np.linalg.svd(points - mean, full_matrices=False)
            # Refine the Hough bin before measuring the entire line.
            for _ in range(2):
                delta = np.column_stack([xx, yy]) - mean
                refined = np.abs(delta @ vt[1]) < 1.5
                refined &= np.abs((direction - angles[i] + 90) % 180 - 90) < 5
                candidates = np.column_stack([xx[refined], yy[refined]]).astype(float)
                along = (candidates - mean) @ vt[0]
                order = np.argsort(along)
                chunks = np.split(order, np.flatnonzero(np.diff(along[order]) > 8) + 1)
                points = candidates[max(chunks, key=len)]
                mean = points.mean(axis=0)
                _, _, vt = np.linalg.svd(points - mean, full_matrices=False)
            pos = (points - mean) @ vt[0]
            length = np.ptp(pos)
            error = np.sqrt(np.mean(((points - mean) @ vt[1]) ** 2))
            if length < max(35, max(g.shape) * .16) or error > 1.25 or len(points) / length < .45:
                continue
            ends = np.array([mean + pos.min() * vt[0], mean + pos.max() * vt[0]])
            # Suppress the same physical edge across neighbouring angle bins.
            for ai, angle in enumerate(angles):
                at = np.radians(angle)
                normal = np.array([np.cos(at), np.sin(at)])
                if abs(normal @ vt[0]) < .08:
                    rho = int(round(mean @ normal)) + diagonal
                    width = int(7 + length * abs(normal @ vt[0]) / 2)
                    votes[ai, max(0, rho-width):rho+width+1] = 0
            if any(f == family and abs((e.mean(axis=0) - mean) @ vt[1]) < 8
                   and abs((e[1]-e[0]) @ vt[1]) / np.linalg.norm(e[1]-e[0]) < .02
                   for f, e, _ in result):
                continue
            result.append((family, ends, length))
    return result


def estimate(a, perspective=False):
    from PIL import Image
    h, w = a.shape[:2]
    scale = min(1, 800 / max(h, w))
    if scale < 1:
        a = np.asarray(Image.fromarray(np.uint8(a.clip(0, 1) * 255)).resize(
            (round(w * scale), round(h * scale)), Image.Resampling.LANCZOS), dtype=np.float32) / 255
    # Long subpixel tracks give less angular bias than quantized Hough peaks.
    # Keep Hough as a fallback when lines are fragmented or partly occluded.
    detected = []
    for family, points in _edge_tracks(a):
        mean = points.mean(axis=0)
        _, _, vt = np.linalg.svd(points - mean, full_matrices=False)
        along = (points - mean) @ vt[0]
        error = np.sqrt(np.mean(((points - mean) @ vt[1])**2))
        if error <= .8:
            ends = np.array([mean + along.min()*vt[0], mean + along.max()*vt[0]])
            detected.append((family, ends, float(np.ptp(along))))
    if len(detected) < 2:
        detected = lines(a)
    if not detected:
        return {"angle": None, "lines": 0, "perspective": False}
    h, w = a.shape[:2]
    radius = np.hypot(w - 1, h - 1) / 2
    centre = np.array([(w - 1) / 2, (h - 1) / 2])
    groups = {}
    for family in ("v", "h"):
        group = [(e - centre) / radius for f, e, _ in detected if f == family]
        axis = 0 if family == "v" else 1
        spread = np.ptp([e[:, axis].mean() for e in group]) if group else 0
        groups[family] = bool(perspective and len(group) >= 2 and spread > .35)
    # A lone family can determine roll and its own convergence, not the other axis.
    active = [0] + ([1] if groups["v"] else []) + ([2] if groups["h"] else [])
    ends = np.array([(e - centre) / radius for _, e, _ in detected])
    vertical = np.array([f == "v" for f, _, _ in detected])
    lengths = np.array([length for _, _, length in detected])

    def residual(values):
        params = np.zeros(3)
        params[active] = values
        m = matrix(*params)
        p = np.concatenate([ends, np.ones((*ends.shape[:2], 1))], axis=2) @ m.T
        p = p[..., :2] / p[..., 2:]
        d = p[:, 1] - p[:, 0]
        return np.where(vertical, d[:, 0], d[:, 1]) / np.linalg.norm(d, axis=1)

    fit = least_squares(residual, np.zeros(len(active)), bounds=(
        [-20] + [-70] * (len(active) - 1), [20] + [70] * (len(active) - 1)),
        loss="soft_l1", f_scale=.008)
    good = np.abs(residual(fit.x)) < np.sin(np.radians(1.2))
    if not good.any() or lengths[good].sum() < .65 * lengths.sum():
        return {"angle": None, "lines": len(detected), "perspective": False}
    # Reject convergence fitted to outliers or insufficient spatial support.
    for family, index in (("v", 1), ("h", 2)):
        if index in active:
            selected = ends[good & (vertical == (family == "v"))]
            axis = 0 if family == "v" else 1
            if len(selected) < 2 or np.ptp(selected[..., axis].mean(axis=1)) < .35:
                return estimate(a, perspective=False)
    params = np.zeros(3)
    params[active] = fit.x
    if abs(params[0]) > 19.5 or np.max(np.abs(params[1:])) > 69:
        return {"angle": None, "lines": len(detected), "perspective": False}
    return {"angle": round(float(params[0]), 1),
            "vertical": round(float(params[1]), 1),
            "horizontal": round(float(params[2]), 1),
            "lines": int(good.sum()), "perspective": len(active) > 1}


def _edge_tracks(a):
    """Trace near-axis edge ridges, allowing smooth curvature and short gaps."""
    g = gaussian_filter(a @ np.array([.2126, .7152, .0722]), 1)
    gx, gy = sobel(g, axis=1), sobel(g, axis=0)
    magnitude = np.hypot(gx, gy)
    threshold = max(.035, float(np.percentile(magnitude, 85)))
    h, w = g.shape
    tracks = []
    for family, major, minor in (("v", gx, gy), ("h", gy.T, gx.T)):
        rows, cols = major.shape
        active = []
        finished = []
        for y in range(6, rows - 6, 3):
            strength = np.abs(major[y])
            candidates = np.flatnonzero((strength[1:-1] > strength[:-2]) &
                                        (strength[1:-1] >= strength[2:]) &
                                        (strength[1:-1] >= threshold)) + 1
            candidates = candidates[(candidates > 6) & (candidates < cols - 7)]
            candidates = candidates[np.abs(minor[y, candidates]) < strength[candidates] * .65]
            peaks = []
            for x in candidates:
                # Quadratic subpixel localization of the edge ridge.
                den = strength[x-1] - 2*strength[x] + strength[x+1]
                offset = .5*(strength[x-1]-strength[x+1])/den if abs(den) > 1e-8 else 0
                peaks.append((x + float(np.clip(offset, -.5, .5)), np.sign(major[y, x])))
            choices = []
            for i, track in enumerate(active):
                pts = track["points"]
                dy = y - pts[-1][1]
                slope = 0 if len(pts) < 3 else (pts[-1][0]-pts[max(0,len(pts)-5)][0]) / (pts[-1][1]-pts[max(0,len(pts)-5)][1])
                predicted = pts[-1][0] + slope * dy
                for j, (x, sign) in enumerate(peaks):
                    distance = abs(x-predicted)
                    if sign == track["sign"] and distance < min(5, 1.5 + .3*dy):
                        choices.append((distance, i, j))
            used_tracks, used_peaks = set(), set()
            for _, i, j in sorted(choices):
                if i not in used_tracks and j not in used_peaks:
                    active[i]["points"].append((peaks[j][0], y))
                    used_tracks.add(i); used_peaks.add(j)
            remaining = []
            for track in active:
                if y - track["points"][-1][1] > 15:
                    finished.append(track)
                else:
                    remaining.append(track)
            active = remaining
            for j, (x, sign) in enumerate(peaks):
                if j not in used_peaks:
                    active.append({"points": [(x, y)], "sign": sign})
        finished.extend(active)
        for track in finished:
            points = np.array(track["points"])
            span = np.ptp(points[:, 1])
            if span < rows*.45 or len(points)*3 < span*.72:
                continue
            if family == "h":
                points = points[:, ::-1]
            # Edge pairs of the same physical stroke are one piece of evidence.
            axis = 0 if family == "v" else 1
            if any(f == family and abs(p[:, axis].mean()-points[:, axis].mean()) < 10
                   for f, p in tracks):
                continue
            tracks.append((family, points))
    return tracks


def _undistort_points(points, k):
    rd = np.linalg.norm(points, axis=1)
    ru = rd.copy()
    for _ in range(12):
        derivative = np.maximum(.1, 1 + 3*k*ru*ru)
        ru = np.clip(ru - (ru*(1+k*ru*ru)-rd)/derivative, 0, 1.8)
    return points * (ru / np.maximum(rd, 1e-8))[:, None]


def _line_error(points):
    centred = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[-1]


def estimate_lens(a):
    """Infer a single radial coefficient from several independently curved edges.

    This is image-based plumb-line calibration, not a camera/lens profile lookup.
    Natural curves and underconstrained scenes must not trigger a lens correction.
    """
    from scipy.optimize import minimize_scalar
    from PIL import Image

    h, w = a.shape[:2]
    if max(h, w) > 900:
        size = (round(w*900/max(h,w)), round(h*900/max(h,w)))
        a = np.asarray(Image.fromarray(np.uint8(a.clip(0,1)*255)).resize(size, Image.Resampling.LANCZOS), np.float32)/255
    h, w = a.shape[:2]
    radius = np.hypot(w-1, h-1)/2
    centre = np.array([(w-1)/2, (h-1)/2])
    candidates = []
    for family, pixels in _edge_tracks(a):
        points = (pixels-centre)/radius
        axis = 0 if family == "v" else 1
        # Central lines contain almost no radial calibration information.
        if abs(points[:, axis].mean()) < .18:
            continue
        def score(k):
            error = _line_error(_undistort_points(points, k))*radius
            return float(np.mean(error**2))
        baseline = score(0)
        fit = minimize_scalar(score, bounds=(-.24, .30), method="bounded", options={"xatol": .0001})
        if (baseline < .15 or fit.fun > baseline*.35 or fit.fun > .5
                or abs(fit.x) < .012 or fit.x < -.235 or fit.x > .295):
            continue
        # Keep each edge estimate separate until cross-edge agreement is checked.
        candidates.append((family, points, float(fit.x), baseline))
    if len(candidates) < 3:
        return {"distortion": None, "lens_lines": 0}
    # Find agreement across independent physical edges before a joint fit.
    group = max(([c for c in candidates if abs(c[2]-seed[2]) < .035]
                 for seed in candidates), key=len)
    offsets = [p.mean(axis=0) for _, p, _, _ in group]
    if len(group) < 3 or len(group) < .7*len(candidates) or np.max(np.ptp(offsets, axis=0)) < .5:
        return {"distortion": None, "lens_lines": 0}
    def joint(k):
        return float(np.mean([np.mean((_line_error(_undistort_points(p,k))*radius)**2)
                              for _,p,_,_ in group]))
    fit = minimize_scalar(joint, bounds=(-.24,.30), method="bounded")
    if fit.fun > joint(0)*.35:
        return {"distortion": None, "lens_lines": 0}
    return {"distortion": round(float(fit.x*300), 1), "lens_lines": len(group)}


def automatic_geometry(a, fallback_distortion=0):
    """Estimate lens curvature, then upright geometry in the original frame units."""
    lens = estimate_lens(a)
    distortion = fallback_distortion if lens["distortion"] is None else lens["distortion"]
    corrected = warp(a, distortion=distortion)
    result = estimate(corrected, perspective=True)
    if result["angle"] is not None:
        ratio = np.hypot(corrected.shape[1]-1, corrected.shape[0]-1) / max(1, np.hypot(a.shape[1]-1, a.shape[0]-1))
        for key in ("vertical", "horizontal"):
            result[key] = round(float(np.clip(result[key]/max(.01,ratio),-100,100)),1)
    if not result["perspective"]:
        # Rotation alone: edge votes level real photos more reliably than the
        # few traced lines, which over-rotate on cluttered scenes.
        voted = level_by_votes(corrected)
        if voted is not None:
            result.update(angle=voted, vertical=0.0, horizontal=0.0)
    result.update(lens)
    return result


def level_by_votes(a):
    """Rotation-only fallback for when too few clean lines are traced.

    Every strong edge votes for how far it leans off the nearest axis; the
    peak is then refined to 0.1° by turning the edge map until its row and
    column projections are sharpest. Returns a clockwise angle or None.
    """
    step = max(1, max(a.shape[:2]) // 1000)
    g = gaussian_filter(a[::step, ::step] @ np.array([.2126, .7152, .0722]), 2)
    gx, gy = sobel(g, axis=1), sobel(g, axis=0)
    mag = np.hypot(gx, gy)
    strong = mag > np.percentile(mag, 90)
    if not mag[strong].sum():
        return None
    lean = (np.degrees(np.arctan2(gy[strong], gx[strong])) + 45) % 90 - 45
    weight = mag[strong] ** 2  # favours long hard edges over texture
    votes, edges = np.histogram(lean, bins=900, range=(-45, 45), weights=weight)
    votes = gaussian_filter1d(votes, 4, mode="wrap")
    centres = (edges[:-1] + edges[1:]) / 2
    # Real tilts are small; a steep peak is usually a roof or a diagonal subject.
    peak = int(np.where(np.abs(centres) <= 20, votes, 0).argmax())
    # shortcut: a fixed peak-to-median ratio, tune against real photos if it misfires.
    if votes[peak] < 3 * np.median(votes):
        return None
    near = np.abs(lean - centres[peak]) < 1
    first = -float(np.average(lean[near], weights=weight[near]))
    sharp = gaussian_filter(a[::step, ::step] @ np.array([.2126, .7152, .0722]), 1)
    edge_map = np.hypot(sobel(sharp, axis=0), sobel(sharp, axis=1))
    h, w = edge_map.shape

    def alignment(degrees):
        # Same trim as straightening: the largest centred same-ratio rectangle.
        t = np.radians(abs(degrees))
        k = min(w / (w * np.cos(t) + h * np.sin(t)), h / (w * np.sin(t) + h * np.cos(t)))
        e = rotate(edge_map, -degrees, reshape=False, order=1)
        nw, nh = int(w * k), int(h * k)
        e = e[(h - nh) // 2 : (h - nh) // 2 + nh, (w - nw) // 2 : (w - nw) // 2 + nw]
        return (e.sum(axis=0) ** 2).mean() + (e.sum(axis=1) ** 2).mean()

    # Every 0.1° step: the alignment curve is too bumpy for a coarse search.
    best = max(np.round(np.arange(first - 1.5, first + 1.51, .1), 1), key=alignment)
    return float(np.clip(best, -45, 45))
