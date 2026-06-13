"""Low-level shapely shape builders shared by the geometry engine.

All coordinates are in **inches** (the IR convention).  Circle and arc
tessellation is adaptive: segment counts are derived from a chord (sagitta)
tolerance so small pads stay cheap while large features keep fidelity.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry

from gerberdiff.types import ArcSegment

# Chord (sagitta) tolerance for circle/arc tessellation: 1 um in inches.
CHORD_TOL_IN = 1e-3 / 25.4

# Bounds for tessellation segment counts (full circle).
_MIN_SEGMENTS = 16
_MAX_SEGMENTS = 256


def circle_segments(radius: float, tol: float = CHORD_TOL_IN) -> int:
    """Segment count for a full circle of *radius* with sagitta <= *tol*.

    sagitta = r * (1 - cos(pi/n))  =>  n >= pi / acos(1 - tol/r)
    """
    if radius <= tol:
        return _MIN_SEGMENTS
    n = math.pi / math.acos(1.0 - tol / radius)
    return max(_MIN_SEGMENTS, min(_MAX_SEGMENTS, math.ceil(n)))


def _quad_segs(radius: float) -> int:
    """quad_segs value for shapely ``buffer`` (segments per quarter circle)."""
    return max(4, math.ceil(circle_segments(radius) / 4))


def circle(x: float, y: float, radius: float) -> BaseGeometry:
    """Filled circle centred at (x, y)."""
    return Point(x, y).buffer(radius, quad_segs=_quad_segs(radius))


def rectangle(x: float, y: float, width: float, height: float) -> BaseGeometry:
    """Axis-aligned filled rectangle centred at (x, y)."""
    w2, h2 = width / 2.0, height / 2.0
    return box(x - w2, y - h2, x + w2, y + h2)


def obround(x: float, y: float, width: float, height: float) -> BaseGeometry:
    """Obround (stadium/capsule): rectangle with semicircular short ends."""
    r = min(width, height) / 2.0
    if width == height:
        return circle(x, y, r)
    if width > height:
        a = (x - (width / 2.0 - r), y)
        b = (x + (width / 2.0 - r), y)
    else:
        a = (x, y - (height / 2.0 - r))
        b = (x, y + (height / 2.0 - r))
    return LineString([a, b]).buffer(r, quad_segs=_quad_segs(r))


def regular_polygon(
    x: float,
    y: float,
    outer_radius: float,
    num_vertices: int,
    rotation_deg: float = 0.0,
) -> BaseGeometry:
    """Regular n-gon centred at (x, y); first vertex at *rotation_deg*.

    Matches the renderer's vertex placement (``_draw_polygon_flash``).
    """
    rot = math.radians(rotation_deg)
    pts = [
        (
            x + outer_radius * math.cos(rot + 2.0 * math.pi * i / num_vertices),
            y + outer_radius * math.sin(rot + 2.0 * math.pi * i / num_vertices),
        )
        for i in range(num_vertices)
    ]
    return Polygon(pts)


def arc_points(arc: ArcSegment, tol: float = CHORD_TOL_IN) -> list[tuple[float, float]]:
    """Sample an :class:`ArcSegment` into a polyline (including both endpoints).

    The ArcSegment convention (``arc_math.py``) is directional and monotonic:
    CCW arcs have ``end_angle_deg > start_angle_deg``; CW arcs have
    ``end_angle_deg < start_angle_deg``.  The sweep is traversed directly --
    no wraparound handling is required.
    """
    sweep = arc.end_angle_deg - arc.start_angle_deg
    n_full = circle_segments(arc.radius, tol)
    n = max(2, math.ceil(n_full * abs(sweep) / 360.0))
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        theta = math.radians(arc.start_angle_deg + sweep * i / n)
        pts.append(
            (
                arc.center_x + arc.radius * math.cos(theta),
                arc.center_y + arc.radius * math.sin(theta),
            )
        )
    return pts
