"""Pure-Python overlays on tightly packed RGB frames.

The CARLA virtual environment used for the real runs has neither Pillow nor
numpy, and this project does not change that environment. The binding frame
must nevertheless carry visible candidate regions and neutral labels, because
the model may only answer with a label. This module therefore draws with plain
Python:

* a 5x7 bitmap font for the candidate letters (A-H) and digits;
* Bresenham lines with optional thickness;
* polygon tint + outline;
* a filled letter badge at the region centre.

Colours are deliberately neutral (cyan/amber/violet), not red/green: the
overlay must not suggest "good/bad" or "vacant/occupied" before the model has
looked at the frame. The tint is light so a real vehicle inside the region
stays visible.

Every function validates the RGB buffer length, so a BGRA/RGBA buffer cannot be
drawn on by accident (the earlier probe's 4-byte stride bug is a test case).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

__all__ = [
    "RGB",
    "CANDIDATE_COLORS",
    "set_pixel",
    "blend_pixel",
    "draw_line",
    "draw_polyline",
    "fill_polygon",
    "draw_polygon",
    "draw_text",
    "text_size",
    "draw_badge",
    "annotate_candidates",
]


RGB = tuple[int, int, int]

#: Neutral, high-contrast candidate palette. No semantic red/green.
CANDIDATE_COLORS: tuple[RGB, ...] = (
    (0, 210, 255),  # cyan
    (255, 185, 0),  # amber
    (190, 130, 255),  # violet
    (120, 230, 160),  # mint
    (255, 140, 190),  # rose
    (150, 200, 255),  # sky
    (230, 220, 120),  # sand
    (200, 200, 200),  # grey
)

_GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ":": ("00000", "00100", "00100", "00000", "00100", "00100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}

_GLYPH_W = 5
_GLYPH_H = 7


def _check_buffer(buf: bytearray, width: int, height: int) -> None:
    if not isinstance(buf, (bytearray, bytes, memoryview)):
        raise TypeError("buf must be a bytes-like object")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("width and height must be positive integers")
    if len(buf) != width * height * 3:
        raise ValueError(
            f"RGB buffer must be exactly {width * height * 3} bytes "
            f"({width}x{height}x3), got {len(buf)}"
        )


def set_pixel(
    buf: bytearray, width: int, height: int, x: int, y: int, color: RGB
) -> None:
    _check_buffer(buf, width, height)
    _check_color(color)
    if 0 <= x < width and 0 <= y < height:
        index = 3 * (y * width + x)
        buf[index : index + 3] = bytes(color)


def blend_pixel(
    buf: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    color: RGB,
    alpha: int,
) -> None:
    _check_buffer(buf, width, height)
    _check_color(color)
    if type(alpha) is not int or not 0 <= alpha <= 255:
        raise ValueError("alpha must be an integer in [0, 255]")
    if not (0 <= x < width and 0 <= y < height):
        return
    index = 3 * (y * width + x)
    old = buf[index : index + 3]
    buf[index : index + 3] = bytes(
        (old[channel] * (255 - alpha) + color[channel] * alpha) // 255
        for channel in range(3)
    )


def _check_color(color: Sequence[int]) -> None:
    if (
        len(color) != 3
        or not all(type(value) is int and 0 <= value <= 255 for value in color)
    ):
        raise ValueError(f"color must be three ints in [0, 255], got {color!r}")


def draw_line(
    buf: bytearray,
    width: int,
    height: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: RGB,
    thickness: int = 1,
) -> None:
    _check_color(color)
    if type(thickness) is not int or thickness < 1:
        raise ValueError("thickness must be a positive integer")
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx - dy
    radius = thickness // 2
    while True:
        for oy in range(-radius, thickness - radius):
            for ox in range(-radius, thickness - radius):
                set_pixel(buf, width, height, x0 + ox, y0 + oy, color)
        if x0 == x1 and y0 == y1:
            break
        doubled = 2 * error
        if doubled > -dy:
            error -= dy
            x0 += sx
        if doubled < dx:
            error += dx
            y0 += sy


def draw_polyline(
    buf: bytearray,
    width: int,
    height: int,
    points: Iterable[Sequence[float]],
    color: RGB,
    *,
    thickness: int = 3,
    closed: bool = True,
) -> None:
    pts = [(float(point[0]), float(point[1])) for point in points]
    if len(pts) < 2:
        raise ValueError("draw_polyline needs at least two points")
    count = len(pts) if closed else len(pts) - 1
    for index in range(count):
        start = pts[index]
        end = pts[(index + 1) % len(pts)]
        draw_line(buf, width, height, start[0], start[1], end[0], end[1], color, thickness)


def _point_in_polygon(x: float, y: float, points: Sequence[Sequence[float]]) -> bool:
    inside = False
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            cross_x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < cross_x:
                inside = not inside
    return inside


def fill_polygon(
    buf: bytearray,
    width: int,
    height: int,
    points: Sequence[Sequence[float]],
    color: RGB,
    *,
    alpha: int = 40,
) -> None:
    _check_color(color)
    if type(alpha) is not int or not 0 <= alpha <= 255:
        raise ValueError("alpha must be an integer in [0, 255]")
    if len(points) < 3:
        raise ValueError("fill_polygon needs at least three points")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min = max(0, int(math.floor(min(xs))))
    x_max = min(width - 1, int(math.ceil(max(xs))))
    y_min = max(0, int(math.floor(min(ys))))
    y_max = min(height - 1, int(math.ceil(max(ys))))
    for y in range(y_min, y_max + 1):
        for x in range(x_min, x_max + 1):
            if _point_in_polygon(x + 0.5, y + 0.5, points):
                blend_pixel(buf, width, height, x, y, color, alpha)


def draw_polygon(
    buf: bytearray,
    width: int,
    height: int,
    points: Sequence[Sequence[float]],
    color: RGB,
    *,
    fill_alpha: int = 36,
    thickness: int = 3,
) -> None:
    if fill_alpha:
        fill_polygon(buf, width, height, points, color, alpha=fill_alpha)
    draw_polyline(buf, width, height, points, color, thickness=thickness)


def text_size(text: str, *, scale: int = 3) -> tuple[int, int]:
    if type(scale) is not int or scale < 1:
        raise ValueError("scale must be a positive integer")
    if not isinstance(text, str) or text == "":
        raise ValueError("text must be a non-empty str")
    return len(text) * (_GLYPH_W + 1) * scale - scale, _GLYPH_H * scale


def draw_text(
    buf: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    color: RGB,
    *,
    scale: int = 3,
) -> tuple[int, int]:
    _check_color(color)
    if type(scale) is not int or scale < 1:
        raise ValueError("scale must be a positive integer")
    if not isinstance(text, str) or text == "":
        raise ValueError("text must be a non-empty str")
    cursor = x
    for char in text.upper():
        glyph = _GLYPHS.get(char)
        if glyph is None:
            raise ValueError(f"unsupported overlay character {char!r}")
        for row_index, row in enumerate(glyph):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                for sy in range(scale):
                    for sx in range(scale):
                        set_pixel(
                            buf,
                            width,
                            height,
                            cursor + column_index * scale + sx,
                            y + row_index * scale + sy,
                            color,
                        )
        cursor += (_GLYPH_W + 1) * scale
    return text_size(text, scale=scale)


def draw_badge(
    buf: bytearray,
    width: int,
    height: int,
    center_x: float,
    center_y: float,
    label: str,
    fill: RGB,
    text_color: RGB = (0, 0, 0),
    *,
    scale: int = 4,
    padding: int = 3,
) -> tuple[int, int, int, int]:
    """Draw a filled letter badge centred on ``(center_x, center_y)``."""

    _check_color(fill)
    _check_color(text_color)
    if type(padding) is not int or padding < 0:
        raise ValueError("padding must be a non-negative integer")
    text_w, text_h = text_size(label, scale=scale)
    box_w = text_w + 2 * padding
    box_h = text_h + 2 * padding
    left = int(round(center_x - box_w / 2.0))
    top = int(round(center_y - box_h / 2.0))
    for y in range(top, top + box_h):
        for x in range(left, left + box_w):
            set_pixel(buf, width, height, x, y, fill)
    draw_text(buf, width, height, left + padding, top + padding, label, text_color, scale=scale)
    return left, top, box_w, box_h


def annotate_candidates(
    buf: bytearray,
    width: int,
    height: int,
    candidates: Sequence[object],
    *,
    fill_alpha: int = 36,
    thickness: int = 3,
    badge_scale: int = 4,
) -> None:
    """Draw each projected candidate and its letter on a real RGB frame.

    ``candidates`` only needs ``label``, ``corners`` and ``center_image``; this
    keeps the function usable with :class:`vln.carla.parking_entities.ProjectedBay`
    without importing it.
    """

    for index, candidate in enumerate(candidates):
        color = CANDIDATE_COLORS[index % len(CANDIDATE_COLORS)]
        corners = getattr(candidate, "corners", None)
        label = getattr(candidate, "label", None)
        center = getattr(candidate, "center_image", None)
        if not corners or not label or center is None:
            raise ValueError("candidate is missing corners/label/center_image")
        draw_polygon(
            buf,
            width,
            height,
            corners,
            color,
            fill_alpha=fill_alpha,
            thickness=thickness,
        )
        draw_badge(
            buf,
            width,
            height,
            center[0],
            center[1],
            str(label),
            color,
            scale=badge_scale,
        )
