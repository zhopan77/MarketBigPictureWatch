"""
Trace the Einnia logo into SVG.

The source is a 264x238 raster drawn on a white plate, so every edge pixel is
a blend of ink and white. Knocking the plate out with a flood fill left those
blends opaque-and-whitish, which is invisible on a light page and shows up as
a white fringe on a dark one. Vector output sidesteps the problem entirely:
there is no baked-in anti-aliasing to fringe, and it stays sharp at any size.

Method
  1. For each flat ink colour F, estimate per-pixel COVERAGE by projecting the
     pixel onto the line between white and F. This recovers the sub-pixel
     coverage the anti-aliasing encodes, instead of thresholding hard.
  2. Upsample that coverage map 4x (bicubic) and threshold at 0.5, so the
     traced outline follows the sub-pixel edge rather than the pixel grid.
  3. potrace each mask into Bezier outlines and emit one <path> per colour.
"""
import pathlib

import numpy as np
from PIL import Image
import potrace

SRC = "/mnt/user-data/uploads/Einnia.png"
UPSAMPLE = 4
WHITE = np.array([255.0, 255.0, 255.0])

# flat ink colours recovered from the source, in draw order
PALETTE = [
    ("red",    (0xde, 0x1d, 0x3a)),
    ("yellow", (0xf6, 0xc2, 0x1e)),
    ("blue",   (0x00, 0x62, 0x9e)),
    ("green",  (0x46, 0xb4, 0x76)),
]


def coverage(arr, F):
    """Per-pixel coverage of ink F over a white plate, in [0,1].

    A blended pixel is P = a*F + (1-a)*W, so a is the projection of (W-P) onto
    (W-F). Solid interior gives 1, a clean background pixel 0, and an edge
    pixel its true fractional coverage."""
    d = WHITE - np.asarray(F, dtype=float)
    num = (WHITE - arr) @ d
    return np.clip(num / float(d @ d), 0.0, 1.0)


def nearest_ink(arr):
    """Index of the palette entry each pixel is closest to (or -1 for white)."""
    cands = [WHITE] + [np.array(c, dtype=float) for _, c in PALETTE]
    d = np.stack([((arr - c) ** 2).sum(axis=2) for c in cands], axis=0)
    return d.argmin(axis=0) - 1


def trace_mask(mask):
    """potrace a boolean mask -> SVG path data, in ORIGINAL pixel units."""
    # potracer's Bitmap.__init__ calls invert() -- it expects IMAGE
    # convention (high = white = background), so an ink mask must be passed
    # complemented, or it traces the background and every path starts with a
    # full-canvas rectangle. Must also be bool: uint8/float take a different
    # threshold path.
    bmp = potrace.Bitmap(~mask)
    path = bmp.trace(turdsize=64, alphamax=1.0, opticurve=True, opttolerance=0.2)
    s = float(UPSAMPLE)
    out = []
    # potracer returns _Point objects with .x/.y rather than tuples
    P = lambda pt: (pt.x / s, pt.y / s)
    for curve in path:
        x, y = P(curve.start_point)
        out.append(f"M{x:.2f},{y:.2f}")
        for seg in curve:
            if seg.is_corner:
                cx, cy = P(seg.c)
                ex, ey = P(seg.end_point)
                out.append(f"L{cx:.2f},{cy:.2f}L{ex:.2f},{ey:.2f}")
            else:
                x1, y1 = P(seg.c1)
                x2, y2 = P(seg.c2)
                ex, ey = P(seg.end_point)
                out.append(f"C{x1:.2f},{y1:.2f} {x2:.2f},{y2:.2f} "
                           f"{ex:.2f},{ey:.2f}")
        out.append("Z")
    return "".join(out)


def build(palette_override=None, mark_only=False):
    im = Image.open(SRC).convert("RGB")
    im = im.crop((0, 0, 264, im.height))          # drop the stray grey band
    if mark_only:
        im = im.crop((0, 0, 264, 168))            # above the wordmark
    arr = np.array(im).astype(float)

    owner = nearest_ink(arr)
    paths = []
    for i, (name, col) in enumerate(PALETTE):
        cov = coverage(arr, col)
        cov[owner != i] = 0.0                      # keep this ink's territory
        big = Image.fromarray((cov * 255).astype(np.uint8)).resize(
            (arr.shape[1] * UPSAMPLE, arr.shape[0] * UPSAMPLE), Image.BICUBIC)
        mask = np.array(big) > 127
        if mask.sum() == 0:
            continue
        d = trace_mask(mask)
        fill = (palette_override or {}).get(name, "#%02x%02x%02x" % col)
        paths.append((name, fill, d))
    return arr.shape, paths


def art_bbox(arr, pad=1):
    """Tight bounds of the inked area, so the viewBox carries no dead margin."""
    ink = nearest_ink(arr) >= 0
    ys, xs = np.where(ink)
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + 1 + pad, arr.shape[1])
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + 1 + pad, arr.shape[0])
    return x0, y0, x1 - x0, y1 - y0


def emit(box, paths, out, label="Einnia"):
    x, y, w, h = box
    body = "\n".join(
        f'  <path fill="{fill}" d="{d}"/>' for _, fill, d in paths)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="{x} {y} {w} {h}" role="img" aria-label="{label}">\n'
           f'{body}\n</svg>\n')
    pathlib.Path(out).write_text(svg, encoding="utf-8")
    return len(svg)


# Dark-theme palette: the brand blue and red fail contrast on the dark paper,
# so they are lifted to clear AA. Yellow and green already pass and are left
# exactly as drawn.
DARK = {"red": "#e74a62", "blue": "#0088dc"}

OUT = "/home/claude/webapp/static"

if __name__ == "__main__":
    im = Image.open(SRC).convert("RGB").crop((0, 0, 264, 238))
    full_box = art_bbox(np.array(im).astype(float))
    mark_box = art_bbox(np.array(im.crop((0, 0, 264, 168))).astype(float))

    for name, override, box, only in [
            ("einnia.svg", None, full_box, False),
            ("einnia-dark.svg", DARK, full_box, False),
            ("einnia-mark.svg", None, mark_box, True)]:
        _, paths = build(palette_override=override, mark_only=only)
        n = emit(box, paths, f"{OUT}/{name}")
        subs = sum(d.count("M") for _, _, d in paths)
        print(f"{name:18s} {n/1024:5.1f} KB  {len(paths)} layers, {subs} subpaths, "
              f"viewBox={box}")
