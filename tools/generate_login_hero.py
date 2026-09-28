"""
Dev-time utility: generate the JewelDesk login hero artwork.

The login page uses a *local* jewellery-showroom visual
(``static/images/login/jewellery-hero.jpg``) instead of an external image
URL, so nothing is fetched at runtime and the asset ships with the repo.

The artwork is drawn (not photographed) but deliberately keeps a premium,
"photographic" feel: a dark, warmly lit jewellery display with a gold chain
necklace and faceted pendant on a bust, a solitaire ring and drop earrings
on velvet, soft bokeh lights, a vignette and film grain. Only abstract,
tasteful jewellery forms are used — no cartoon styling, no bright colours.

Requires Pillow (already present in the project virtualenv as a ReportLab
dependency). This module is a *development* helper only — Django never
imports it, so no runtime dependency is added to ``requirements.txt``.

Usage (from the project root):

    .\\venv\\Scripts\\python.exe tools\\generate_login_hero.py
    .\\venv\\Scripts\\python.exe tools\\generate_login_hero.py --preview preview.png
"""

from __future__ import annotations

import argparse
import math
import os
import random
from typing import Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

# ---------------------------------------------------------------------------
# Canvas configuration
# ---------------------------------------------------------------------------
# Everything is drawn at SS x the final size and then downsampled, which keeps
# edges smooth without antialiasing tricks.
SS = 2
W, H = 1300, 1650          # final size in pixels (portrait 4:5)
CW, CH = W * SS, H * SS    # drawing canvas size

RGB = Tuple[int, int, int]
Stop = Tuple[float, str]

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'images', 'login', 'jewellery-hero.jpg',
)

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def hx(value: str) -> RGB:
    """``'#d4a843'`` -> ``(212, 168, 67)``."""
    value = value.lstrip('#')
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def sample(stops: Sequence[Stop], t: float) -> RGB:
    """Sample a colour from ``stops`` (positions in 0..1) at ``t``."""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if t <= p1:
            if p1 <= p0:
                return hx(c1)
            return lerp(hx(c0), hx(c1), (t - p0) / (p1 - p0))
    return hx(stops[-1][1])


def apply_stops(gray: Image.Image, stops: Sequence[Stop]) -> Image.Image:
    """Map a greyscale image through a multi-stop colour ramp."""
    channels = []
    for channel in range(3):
        table = [sample(stops, v / 255.0)[channel] for v in range(256)]
        channels.append(gray.point(table))
    return Image.merge('RGB', channels)


def ramp(width: int, height: int, angle: str) -> Image.Image:
    """Greyscale 0..255 ramp: ``v`` vertical, ``h`` horizontal, ``d`` diagonal."""
    small = 96
    img = Image.new('L', (small, small))
    px = img.load()
    for j in range(small):
        for i in range(small):
            if angle == 'v':
                t = j / (small - 1)
            elif angle == 'h':
                t = i / (small - 1)
            else:
                t = (i + j) / (2 * (small - 1))
            px[i, j] = int(255 * t)
    return img.resize((width, height), Image.Resampling.BICUBIC)


def radial_mask(size: Tuple[int, int], centre: Tuple[float, float],
                radius: float, invert: bool = False) -> Image.Image:
    """Soft circular falloff mask (1 at the centre, 0 at ``radius``)."""
    total_w, total_h = size
    small = 160
    mask = Image.new('L', (small, small))
    px = mask.load()
    sx = total_w / small
    sy = total_h / small
    cx, cy = centre
    for j in range(small):
        for i in range(small):
            dx = (i + 0.5) * sx - cx
            dy = (j + 0.5) * sy - cy
            d = math.hypot(dx, dy) / radius
            v = 1.0 - d
            v = 0.0 if v < 0 else (1.0 if v > 1 else v)
            v = v * v * (3 - 2 * v)
            if invert:
                v = 1.0 - v
            px[i, j] = int(255 * v)
    return mask.resize(size, Image.Resampling.BICUBIC)


def mask_canvas() -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    """A fresh drawing surface: greyscale mask plus its ImageDraw handle."""
    mask = Image.new('L', (CW, CH), 0)
    return mask, ImageDraw.Draw(mask)


def blur(mask: Image.Image, radius: float) -> Image.Image:
    """Blur, with ``radius`` expressed in final pixels (scaled by SS)."""
    return mask.filter(ImageFilter.GaussianBlur(max(0.1, radius * SS)))


def paste_metal(canvas: Image.Image, mask: Image.Image, stops: Sequence[Stop],
                angle: str = 'd', softness: float = 0.7,
                glow: float = 0.0) -> None:
    """Paste ``mask`` filled with a metallic multi-stop ramp onto the canvas."""
    box = mask.getbbox()
    if not box:
        return
    pad = int(8 * SS)
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(CW, box[2] + pad), min(CH, box[3] + pad))
    tile = mask.crop(box)
    if softness:
        tile = tile.filter(ImageFilter.GaussianBlur(softness * SS))
    metal = apply_stops(ramp(tile.width, tile.height, angle), stops)
    if glow:
        halo = tile.filter(ImageFilter.GaussianBlur(glow * SS))
        halo = halo.point(lambda v: int(v * 0.5))
        canvas.paste(metal, (box[0], box[1]), halo)
    canvas.paste(metal, (box[0], box[1]), tile)


def paste_specular(canvas: Image.Image, mask: Image.Image,
                   colour: RGB = (255, 246, 214),
                   shift: Tuple[int, int] = (0, -2), opacity: float = 0.55,
                   softness: float = 0.6) -> None:
    """Bright rim along the top edge of a shape (fakes the key light)."""
    shifted = ImageChops.offset(mask, int(shift[0] * SS), int(shift[1] * SS))
    edge = ImageChops.subtract(shifted, mask)
    if softness:
        edge = edge.filter(ImageFilter.GaussianBlur(softness * SS))
    edge = edge.point(lambda v: int(v * opacity))
    canvas.paste(Image.new('RGB', (CW, CH), colour), (0, 0), edge)


def paste_shadow(canvas: Image.Image, mask: Image.Image, opacity: float = 0.55,
                 softness: float = 8.0, shift: Tuple[int, int] = (0, 3)) -> None:
    """Dark, blurred copy of ``mask`` behind a shape (contact shadow)."""
    shadow = ImageChops.offset(mask, int(shift[0] * SS), int(shift[1] * SS))
    shadow = blur(shadow, softness).point(lambda v: int(v * opacity))
    canvas.paste(Image.new('RGB', (CW, CH), (5, 3, 2)), (0, 0), shadow)


def paste_glow(canvas: Image.Image, centre: Tuple[float, float], radius: float,
               colour: RGB, alpha: float, aspect: float = 1.0) -> None:
    """Soft light bloom — showroom spotlights and out-of-focus highlights.

    The falloff is evaluated on a small tile and scaled up, so blurs stay
    cheap even on the large drawing canvas.
    """
    width = int(2 * radius * SS)
    height = int(width / aspect)
    small = 72
    mask = Image.new('L', (small, small))
    px = mask.load()
    for j in range(small):
        dy = (j + 0.5) / small * 2 - 1
        for i in range(small):
            dx = (i + 0.5) / small * 2 - 1
            d = math.hypot(dx, dy)
            v = 1.0 - d
            v = 0.0 if v < 0 else (1.0 if v > 1 else v)
            px[i, j] = int(255 * v * v * (3 - 2 * v))
    mask = mask.resize((width, height), Image.Resampling.BICUBIC)
    mask = mask.point(lambda v: int(v * alpha))
    canvas.paste(Image.new('RGB', (width, height), colour),
                 (int(centre[0] * SS - width / 2), int(centre[1] * SS - height / 2)),
                 mask)


def catenary(x0: float, y0: float, x1: float, y1: float, sag: float,
             steps: int = 120) -> list:
    """Hanging curve (chain) from (x0,y0) to (x1,y1) dipping by ``sag``."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t + sag * math.sin(math.pi * t)
        pts.append((x, y))
    return pts


def ellipse_tile(px: float, py: float, rx: float, ry: float, angle: float,
                 line: float) -> Tuple[Image.Image, Tuple[int, int]]:
    """Render one rotated chain link and return it with its paste offset."""
    size = int(max(rx, ry) * 2.6 * SS)
    tile = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(tile)
    c = size / 2
    draw.ellipse((c - rx * SS, c - ry * SS, c + rx * SS, c + ry * SS),
                 outline=255, width=max(1, int(line * SS)))
    tile = tile.rotate(angle, resample=Image.Resampling.BICUBIC)
    return tile, (int(px * SS - size / 2), int(py * SS - size / 2))

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
BG_STOPS: Sequence[Stop] = (
    (0.00, '#2a1e15'), (0.30, '#1e1510'), (0.62, '#150e0b'), (1.00, '#090606'),
)

VELVET_STOPS: Sequence[Stop] = (
    (0.00, '#5c3c21'), (0.09, '#4a2e18'), (0.28, '#33200f'), (0.60, '#20130a'),
    (1.00, '#110a06'),
)

# Dark bronze display stand with a warm specular edge.
STAND_STOPS: Sequence[Stop] = (
    (0.00, '#7d5a22'), (0.20, '#4a3313'), (0.48, '#2a1c0b'), (0.74, '#1a1107'),
    (1.00, '#0e0905'),
)

# Polished-gold reflections: alternating light/dark bands read as metal.
GOLD_STOPS: Sequence[Stop] = (
    (0.00, '#3a290c'), (0.15, '#946722'), (0.31, '#e6c273'), (0.45, '#fff6db'),
    (0.58, '#e0b761'), (0.76, '#8d611f'), (1.00, '#33230a'),
)
GOLD_SOFT_STOPS: Sequence[Stop] = (
    (0.00, '#4d3814'), (0.30, '#c49a4a'), (0.50, '#f4e0b0'), (0.70, '#b2863a'),
    (1.00, '#412d0e'),
)
GEM_STOPS: Sequence[Stop] = (
    (0.00, '#a8925f'), (0.25, '#f2e7c9'), (0.48, '#ffffff'), (0.62, '#e8dcc0'),
    (0.82, '#9d8a5e'), (1.00, '#5c4f34'),
)


# ---------------------------------------------------------------------------
# Scene: background, velvet display table, jewellery bust
# ---------------------------------------------------------------------------


def draw_background(canvas: Image.Image) -> None:
    """Deep, warm showroom interior with soft spotlight pools."""
    canvas.paste(apply_stops(ramp(CW, CH, 'v'), BG_STOPS), (0, 0))
    paste_glow(canvas, (520, 150), 860, hx('#c08a33'), 0.30)
    paste_glow(canvas, (1130, 690), 620, hx('#8a6122'), 0.20)
    paste_glow(canvas, (170, 1080), 520, hx('#8a6122'), 0.16)


def draw_velvet(canvas: Image.Image) -> None:
    """Draped velvet display surface with soft folds and a warm sheen."""
    top = 1168.0
    wave = [(i * SS, (top + 16 * math.sin(i / 130.0)) * SS)
            for i in range(0, W + 20, 10)]
    mask, draw = mask_canvas()
    draw.polygon(wave + [(CW, CH), (0, CH)], fill=255)
    paste_metal(canvas, mask, VELVET_STOPS, angle='v', softness=1.0)

    # Folds: drawn small and scaled up so they stay soft and silky.
    small = Image.new('L', (CW // 10, CH // 10), 0)
    sd = ImageDraw.Draw(small)
    random.seed(11)
    x = 0
    while x < small.width:
        width = random.randint(3, 10)
        sd.rectangle((x, int(top / 10) - 4, x + width, small.height),
                     fill=random.randint(80, 190))
        x += width + random.randint(2, 8)
    folds = small.filter(ImageFilter.GaussianBlur(4)).resize(
        (CW, CH), Image.Resampling.BICUBIC)
    folds = ImageChops.multiply(folds, mask).point(lambda v: int(v * 0.85))
    canvas.paste(Image.new('RGB', (CW, CH), (14, 8, 4)), (0, 0), folds)

    # Bright lip where the velvet meets the dark room, plus a warm light pool.
    band, band_draw = mask_canvas()
    band_draw.polygon(wave + [(x, y + 34 * SS) for x, y in reversed(wave)],
                      fill=255)
    paste_specular(canvas, band, colour=(255, 219, 158), shift=(0, -4),
                   opacity=0.30, softness=1.6)
    paste_glow(canvas, (620, 1175), 560, hx('#c08a33'), 0.22)


# ---------------------------------------------------------------------------
# Scene: necklaces, pendant gem, sparkle
# ---------------------------------------------------------------------------


def paste_mask(canvas: Image.Image, mask: Image.Image, colour: RGB,
               opacity: float = 1.0, softness: float = 0.0,
               shift: Tuple[int, int] = (0, 0)) -> None:
    """Paste a flat colour through an arbitrary mask (cropped, cheap blur)."""
    if shift != (0, 0):
        mask = ImageChops.offset(mask, int(shift[0] * SS), int(shift[1] * SS))
    box = mask.getbbox()
    if not box:
        return
    pad = int(6 * SS)
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(CW, box[2] + pad), min(CH, box[3] + pad))
    tile = mask.crop(box)
    if softness:
        tile = tile.filter(ImageFilter.GaussianBlur(softness * SS))
    canvas.paste(Image.new('RGB', tile.size, colour), (box[0], box[1]),
                 tile.point(lambda v: int(v * opacity)))


def _walk(points: Sequence[Tuple[float, float]], distance: float):
    """Position + screen tangent angle at ``distance`` along a polyline."""
    remaining = distance
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= 1e-6:
            continue
        if remaining <= seg:
            t = remaining / seg
            return ((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t),
                    math.degrees(math.atan2(y1 - y0, x1 - x0)))
        remaining -= seg
    x, y = points[-1]
    x0, y0 = points[-2]
    return (x, y), math.degrees(math.atan2(y - y0, x - x0))


def draw_chain(mask: Image.Image, points: Sequence[Tuple[float, float]],
               link_len: float = 36.0, link_wid: float = 24.0,
               line: float = 3.4) -> None:
    """Interlocking rotated ellipse links along a hanging curve."""
    total = sum(math.hypot(points[i + 1][0] - points[i][0],
                           points[i + 1][1] - points[i][1])
                for i in range(len(points) - 1))
    spacing = link_len * 0.60
    index = 0
    distance = 0.0
    while distance <= total:
        (px, py), angle = _walk(points, distance)
        if index % 2 == 0:
            rx, ry = link_len / 2, link_wid / 2
        else:
            rx, ry = link_wid / 2, link_len / 2
        tile, box = ellipse_tile(px, py, rx, ry, -angle, line)
        mask.paste(tile, box, tile)
        index += 1
        distance += spacing


def draw_necklaces(canvas: Image.Image) -> None:
    """Necklaces draped over a jewellery display stand, with a pendant."""
    # 1. Stand post and foot (behind the chains).
    for part in (_rounded_rect(636, 664, 664, 1196, 10),
                 _rounded_rect(552, 1174, 748, 1222, 18)):
        paste_shadow(canvas, part, opacity=0.5, softness=6.0, shift=(4, 7))
        paste_metal(canvas, part, STAND_STOPS, angle='h', softness=0.7)
        paste_specular(canvas, part, colour=(240, 214, 158), shift=(-1.5, -1.5),
                       opacity=0.40, softness=0.7)

    # 2. Two layered chains draped over the stand.
    main = catenary(400, 646, 900, 646, 372)
    upper = catenary(492, 646, 808, 646, 300)
    chain = Image.new('L', (CW, CH), 0)
    draw_chain(chain, upper, link_len=30.0, link_wid=20.0, line=3.0)
    draw_chain(chain, main, link_len=36.0, link_wid=24.0, line=3.4)
    paste_shadow(canvas, chain, opacity=0.55, softness=5.0, shift=(0, 4))
    paste_metal(canvas, chain, GOLD_STOPS, angle='v', softness=0.55)
    paste_specular(canvas, chain, colour=(255, 244, 206), shift=(0, -1.5),
                   opacity=0.60, softness=0.5)

    # 3. The T-bar in front of the chain ends, then the pendant in front of
    #    the post.
    bar = _rounded_rect(366, 638, 934, 680, 21)
    paste_shadow(canvas, bar, opacity=0.45, softness=5.0, shift=(0, 5))
    paste_metal(canvas, bar, STAND_STOPS, angle='v', softness=0.7)
    paste_specular(canvas, bar, colour=(240, 214, 158), shift=(0, -2),
                   opacity=0.45, softness=0.7)

    draw_pendant(canvas, 650, 1082, 146, 186)


def _rounded_rect(x0: float, y0: float, x1: float, y1: float,
                  radius: float) -> Image.Image:
    """Rounded-rectangle mask in base coordinates."""
    mask, draw = mask_canvas()
    draw.rounded_rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS),
                           radius=radius * SS, fill=255)
    return mask


def pear_outline(cx: float, cy: float, width: float, height: float,
                 steps: int = 96) -> list:
    """Teardrop outline: round crown on top, gentle taper to a point below."""
    radius = width / 2.0
    crown_y = cy - height * 0.16
    shoulder = crown_y + radius * 1.05
    tip_y = cy + height * 0.54
    span = max(1.0, tip_y - shoulder)
    halves = []
    for i in range(steps + 1):
        y = crown_y + (tip_y - crown_y) * (i / steps)
        if y <= shoulder:
            k = max(0.0, 1.0 - ((y - crown_y) / radius) ** 2)
            halves.append(radius * math.sqrt(k))
        else:
            halves.append(radius * max(0.0, 1.0 - (y - shoulder) / span) ** 0.75)
    left = [(cx - half, crown_y + (tip_y - crown_y) * (i / steps))
            for i, half in enumerate(halves)]
    right = [(cx + half, crown_y + (tip_y - crown_y) * (i / steps))
             for i, half in reversed(list(enumerate(halves)))]
    return left + right



def draw_pendant(canvas: Image.Image, cx: float, cy: float, width: float,
                 height: float) -> None:
    """Oval gold bezel pendant with a faceted champagne gem."""
    rx, ry = width / 2.0, height / 2.0

    outer, outer_draw = mask_canvas()
    outer_draw.ellipse((cx * SS - rx * SS, cy * SS - ry * SS,
                        cx * SS + rx * SS, cy * SS + ry * SS), fill=255)
    inner, inner_draw = mask_canvas()
    inner_draw.ellipse((cx * SS - rx * 0.62 * SS, cy * SS - ry * 0.62 * SS,
                        cx * SS + rx * 0.62 * SS, cy * SS + ry * 0.62 * SS),
                       fill=255)
    frame = ImageChops.subtract(outer, inner)

    bail, bail_draw = mask_canvas()
    bail_draw.ellipse(((cx - 15) * SS, (cy - ry - 34) * SS,
                       (cx + 15) * SS, (cy - ry + 4) * SS),
                      outline=255, width=int(4.0 * SS))

    paste_shadow(canvas, outer, opacity=0.55, softness=9.0, shift=(0, 6))
    paste_metal(canvas, bail, GOLD_SOFT_STOPS, angle='d', softness=0.5)
    paste_metal(canvas, frame, GOLD_STOPS, angle='d', softness=0.5)
    paste_specular(canvas, frame, colour=(255, 247, 214), shift=(-2, -2),
                   opacity=0.55, softness=0.6)

    # Faceted gem inside the bezel.
    box = inner.getbbox()
    if not box:
        return
    tile = Image.new('RGB', (box[2] - box[0], box[3] - box[1]), hx('#efe3c6'))
    tdraw = ImageDraw.Draw(tile)
    ox, oy = -box[0], -box[1]
    gem_rx, gem_ry = rx * 0.62, ry * 0.62
    centroid = (cx + ox, cy - gem_ry * 0.16 + oy)
    rim = [(cx + ox + gem_rx * math.cos(math.radians(a)),
            cy + oy + gem_ry * math.sin(math.radians(a)))
           for a in range(0, 360, 18)]
    tones = ('#fffdf4', '#d9c184', '#fbf0cd', '#c3a765', '#fffbe8',
             '#e0ca92', '#fdf5da', '#b99e5c')
    for i in range(len(rim)):
        tdraw.polygon([centroid, rim[i], rim[(i + 1) % len(rim)]],
                      fill=hx(tones[i % len(tones)]))
    table = [(centroid[0] + gem_rx * 0.44 * math.cos(math.radians(a)),
              centroid[1] + gem_ry * 0.44 * math.sin(math.radians(a)))
             for a in range(0, 360, 45)]
    tdraw.polygon(table, fill=hx('#fffefa'))
    canvas.paste(tile, (box[0], box[1]), inner.crop(box))

    edges, edge_draw = mask_canvas()
    edge_draw.ellipse((cx * SS - gem_rx * 0.44 * SS, cy * SS - gem_ry * 0.44 * SS,
                       cx * SS + gem_rx * 0.44 * SS, cy * SS + gem_ry * 0.44 * SS),
                      outline=110, width=max(1, int(0.9 * SS)))
    for i in range(len(table)):
        target = rim[min(len(rim) - 1, int((i + 0.5) * len(rim) / len(table)))]
        edge_draw.line([(table[i][0] - ox, table[i][1] - oy),
                        (target[0] - ox, target[1] - oy)],
                       fill=150, width=max(1, int(1.0 * SS)))
    paste_mask(canvas, ImageChops.multiply(edges, inner),
               (96, 78, 44), opacity=0.55)

    gem_edge = ImageChops.subtract(
        inner, inner.resize((CW // 4, CH // 4), Image.Resampling.BILINEAR)
        .resize((CW, CH), Image.Resampling.BICUBIC))
    paste_mask(canvas, gem_edge, (62, 50, 30), opacity=0.55)

    # Facet sheen across the upper-left of the stone, then the glint.
    sheen = ImageChops.multiply(inner, radial_mask(
        (CW, CH), ((cx - gem_rx * 0.35) * SS, (cy - gem_ry * 0.45) * SS),
        gem_rx * 0.9 * SS))
    paste_mask(canvas, sheen, (255, 252, 238), opacity=0.30)
    paste_glow(canvas, (cx - gem_rx * 0.30, cy - gem_ry * 0.42),
               gem_rx * 0.55, (255, 252, 238), 0.35)
    draw_sparkle(canvas, cx - gem_rx * 0.34, cy - gem_ry * 0.48, 32, 0.95)


def draw_sparkle(canvas: Image.Image, x: float, y: float, size: float = 26.0,
                 strength: float = 0.9) -> None:
    """Four-point light glint (polished-metal specular sparkle)."""
    mask, draw = mask_canvas()
    narrow = size * 0.13
    draw.polygon([(x * SS, (y - size) * SS), ((x + narrow) * SS, y * SS),
                  (x * SS, (y + size) * SS), ((x - narrow) * SS, y * SS)],
                 fill=255)
    draw.polygon([((x - size) * SS, y * SS), (x * SS, (y + narrow) * SS),
                  ((x + size) * SS, y * SS), (x * SS, (y - narrow) * SS)],
                 fill=255)
    paste_mask(canvas, mask, (255, 255, 255), opacity=strength, softness=0.4)
    paste_mask(canvas, mask, (255, 238, 196), opacity=strength * 0.30,
               softness=size * 0.30)


# ---------------------------------------------------------------------------
# Scene: rings and drop earrings on the velvet, bokeh, finishing
# ---------------------------------------------------------------------------


def shape_tile(width: float, height: float, angle: float, draw_fn) -> Image.Image:
    """Draw a shape on its own tile (canvas pixels) and rotate it."""
    pad = 1.45
    tile = Image.new('L', (int(width * pad * SS), int(height * pad * SS)), 0)
    handle = ImageDraw.Draw(tile)
    draw_fn(handle, tile.width / 2.0, tile.height / 2.0)
    return tile.rotate(angle, resample=Image.Resampling.BICUBIC)


def place_tile(mask: Image.Image, tile: Image.Image, cx: float, cy: float) -> None:
    """Paste a rotated tile mask centred on ``(cx, cy)`` in base coordinates."""
    mask.paste(tile, (int(cx * SS - tile.width / 2),
                      int(cy * SS - tile.height / 2)), tile)


def draw_ring_band(mask: Image.Image, cx: float, cy: float, rx: float, ry: float,
                   band: float, angle: float) -> None:
    """Gold torus band seen at a slight angle."""

    def band_shape(handle: ImageDraw.ImageDraw, mx: float, my: float) -> None:
        handle.ellipse((mx - rx * SS, my - ry * SS, mx + rx * SS, my + ry * SS),
                       outline=255, width=max(2, int(band * SS)))

    place_tile(mask, shape_tile(rx * 2, ry * 2, angle, band_shape), cx, cy)


def draw_brilliant(canvas: Image.Image, cx: float, cy: float, table_r: float,
                   girdle_r: float) -> None:
    """Top-down brilliant-cut stone: table, crown facets and gold prongs."""
    size = girdle_r * 2.6
    tile = Image.new('RGB', (int(size * SS), int(size * SS)), hx('#efe7d2'))
    handle = ImageDraw.Draw(tile)
    mx, my = tile.width / 2.0, tile.height / 2.0
    girdle = [(mx + girdle_r * SS * math.cos(math.radians(a)),
               my + girdle_r * SS * math.sin(math.radians(a)))
              for a in range(0, 360, 30)]
    table = [(mx + table_r * SS * math.cos(math.radians(a)),
              my + table_r * SS * math.sin(math.radians(a)))
             for a in range(0, 360, 45)]
    tones = ('#fffefa', '#cfdcea', '#ffffff', '#c2d1e3', '#f4f9ff', '#d3dfec')
    for i in range(len(girdle)):
        a = girdle[i]
        b = girdle[(i + 1) % len(girdle)]
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        nearest = min(table, key=lambda p: (p[0] - middle[0]) ** 2
                      + (p[1] - middle[1]) ** 2)
        handle.polygon([nearest, a, b], fill=hx(tones[i % len(tones)]))
        handle.line([nearest, a], fill=hx('#9aa8b8'), width=max(1, int(0.7 * SS)))
    handle.polygon(table, fill=hx('#ffffff'))
    handle.line(girdle + [girdle[0]], fill=hx('#8d9aa8'),
                width=max(1, int(1.1 * SS)))

    gem_mask = Image.new('L', tile.size, 0)
    ImageDraw.Draw(gem_mask).polygon(girdle, fill=255)
    canvas.paste(tile, (int(cx * SS - mx), int(cy * SS - my)), gem_mask)

    prongs, prong_draw = mask_canvas()
    for a in range(20, 360, 90):
        px = cx + girdle_r * 1.14 * math.cos(math.radians(a))
        py = cy + girdle_r * 1.14 * math.sin(math.radians(a))
        prong_draw.ellipse(((px - 6) * SS, (py - 6) * SS,
                            (px + 6) * SS, (py + 6) * SS), fill=255)
    paste_metal(canvas, prongs, GOLD_SOFT_STOPS, angle='d', softness=0.6)




def draw_rings(canvas: Image.Image) -> None:
    """A solitaire ring and a plain band resting on the velvet."""
    plain, _ = mask_canvas()
    draw_ring_band(plain, 812, 1386, 76, 50, 15, -18)

    solitaire, _ = mask_canvas()
    draw_ring_band(solitaire, 992, 1288, 88, 60, 17, 12)

    paste_shadow(canvas, plain, opacity=0.5, softness=9.0, shift=(3, 6))
    paste_shadow(canvas, solitaire, opacity=0.5, softness=9.0, shift=(3, 6))
    paste_metal(canvas, plain, GOLD_STOPS, angle='d', softness=0.6)
    paste_metal(canvas, solitaire, GOLD_STOPS, angle='d', softness=0.6)
    paste_specular(canvas, plain, colour=(255, 246, 214), shift=(0, -1.6),
                   opacity=0.5, softness=0.5)
    paste_specular(canvas, solitaire, colour=(255, 246, 214), shift=(0, -1.6),
                   opacity=0.5, softness=0.5)

    paste_glow(canvas, (992, 1204), 66, (255, 250, 232), 0.28)
    draw_brilliant(canvas, 992, 1204, 26, 40)
    draw_sparkle(canvas, 972, 1186, 34, 0.9)


def drop_earring_tile(width: float, height: float, angle: float) -> Image.Image:
    """Teardrop earring (drop + hook) on a rotated tile."""
    size = int(max(width, height) * 1.75 * SS)
    tile = Image.new('L', (size, size), 0)
    handle = ImageDraw.Draw(tile)
    mx = my = size / 2.0
    pts = pear_outline(mx / SS, my / SS + height * 0.10, width, height, steps=64)
    handle.polygon([(x * SS, y * SS) for x, y in pts], fill=255)
    handle.ellipse((mx - 9 * SS, my - height * 0.20 * SS,
                    mx + 9 * SS, my + height * 0.02 * SS),
                   outline=255, width=max(2, int(2.6 * SS)))
    return tile.rotate(angle, resample=Image.Resampling.BICUBIC)


def draw_earrings(canvas: Image.Image) -> None:
    """A pair of gold drop earrings resting on the velvet (slightly blurred)."""
    for cx, cy, scale, angle, soft in ((622.0, 1308.0, 1.05, 14.0, 1.2),
                                       (716.0, 1350.0, 0.98, 34.0, 1.8)):
        ear, _ = mask_canvas()
        place_tile(ear, drop_earring_tile(44 * scale, 108 * scale, angle), cx, cy)
        paste_shadow(canvas, ear, opacity=0.5, softness=7.0, shift=(2, 5))
        paste_metal(canvas, ear, GOLD_SOFT_STOPS, angle='d', softness=soft)
        paste_specular(canvas, ear, colour=(255, 246, 214), shift=(-2, -2),
                       opacity=0.55, softness=0.9)

    draw_sparkle(canvas, 600, 1276, 18, 0.55)


def draw_bokeh(canvas: Image.Image) -> None:
    """Out-of-focus warm highlights — showroom lights behind the display."""
    random.seed(17)
    palette = ((255, 216, 146), (255, 233, 190), (216, 166, 86),
               (255, 244, 214), (224, 180, 104))
    for _ in range(26):
        paste_glow(canvas, (random.uniform(-30, W + 30), random.uniform(-30, 1120)),
                   random.uniform(18, 92), random.choice(palette),
                   random.uniform(0.04, 0.11))

    # Light falling into the display case: two long, soft streaks.
    paste_glow(canvas, (330, 120), 900, (255, 226, 172), 0.06, aspect=4.2)
    paste_glow(canvas, (1180, 90), 820, (255, 232, 186), 0.05, aspect=3.6)

def finish(canvas: Image.Image) -> Image.Image:
    """Vignette, warm grade, film grain, then downsample to the final size."""
    vignette = radial_mask((CW, CH), (CW / 2, CH * 0.44), 900 * SS, invert=True)
    vignette = vignette.point(lambda v: int(v * 0.44))
    canvas.paste(Image.new('RGB', (CW, CH), (5, 3, 2)), (0, 0), vignette)

    # Warm colour grade: a touch of amber over the whole frame.
    canvas.paste(Image.new('RGB', (CW, CH), (72, 42, 14)), (0, 0),
                 Image.new('L', (CW, CH), 22))

    final = canvas.convert('RGB')
    noise = Image.effect_noise((CW, CH), 13).convert('RGB')
    final = Image.blend(final, noise, 0.035)
    final = final.resize((W, H), Image.Resampling.LANCZOS)
    # The page overlays this image with a dark/gold scrim, so lift the
    # exposure slightly to keep the jewellery readable underneath it.
    final = ImageEnhance.Brightness(final).enhance(1.08)
    final = ImageEnhance.Contrast(final).enhance(1.06)
    return final.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55,
                                                threshold=3))


def build(preview: str = '', out_path: str = OUT_PATH) -> str:
    """Draw the whole scene and write the JPEG hero image."""
    canvas = Image.new('RGB', (CW, CH), (10, 7, 5))
    draw_background(canvas)
    draw_velvet(canvas)
    # Depth of field: the room and display surface stay soft, the jewellery
    # itself is drawn sharply on top of the blurred background.
    canvas = canvas.filter(ImageFilter.GaussianBlur(1.6 * SS))
    draw_bokeh(canvas)
    draw_necklaces(canvas)
    draw_rings(canvas)
    draw_earrings(canvas)
    final = finish(canvas)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    final.save(out_path, 'JPEG', quality=86, optimize=True, progressive=True)
    if preview:
        os.makedirs(os.path.dirname(os.path.abspath(preview)), exist_ok=True)
        final.resize((W // 3, H // 3), Image.Resampling.LANCZOS).save(preview)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Generate the JewelDesk login hero artwork.')
    parser.add_argument('--out', default=OUT_PATH,
                        help='JPEG output path (default: %(default)s)')
    parser.add_argument('--preview', default='',
                        help='optional preview image path for inspection')
    args = parser.parse_args()
    path = build(args.preview, args.out)
    print('wrote', path, os.path.getsize(path) // 1024, 'KB')


if __name__ == '__main__':
    main()

