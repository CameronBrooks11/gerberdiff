"""Tests for geometry/primitives.py: adaptive tessellation and shape areas."""

from __future__ import annotations

import math

from gerberdiff.geometry.primitives import (
    CHORD_TOL_IN,
    arc_points,
    circle,
    circle_segments,
    obround,
    rectangle,
    regular_polygon,
)
from gerberdiff.types import ArcSegment

# ---------------------------------------------------------------------------
# circle_segments
# ---------------------------------------------------------------------------


def test_circle_segments_minimum_floor() -> None:
    assert circle_segments(1e-9) == 16
    assert circle_segments(CHORD_TOL_IN / 2.0) == 16


def test_circle_segments_monotonic_with_radius() -> None:
    radii = [0.001, 0.01, 0.1, 1.0, 10.0]
    counts = [circle_segments(r) for r in radii]
    assert counts == sorted(counts)


def test_circle_segments_capped() -> None:
    assert circle_segments(1000.0) == 256


def test_circle_segments_meets_chord_tolerance() -> None:
    """For mid-range radii the sagitta must actually be <= tolerance."""
    for r in (0.005, 0.02, 0.05):
        n = circle_segments(r)
        if n in (16, 256):
            continue  # clamped: tolerance bound does not apply
        sagitta = r * (1.0 - math.cos(math.pi / n))
        assert sagitta <= CHORD_TOL_IN * 1.0001


# ---------------------------------------------------------------------------
# Shape areas
# ---------------------------------------------------------------------------


def test_circle_area() -> None:
    r = 0.05
    geom = circle(0.0, 0.0, r)
    assert math.isclose(geom.area, math.pi * r * r, rel_tol=5e-3)


def test_circle_position() -> None:
    geom = circle(1.0, -2.0, 0.1)
    c = geom.centroid
    assert math.isclose(c.x, 1.0, abs_tol=1e-9)
    assert math.isclose(c.y, -2.0, abs_tol=1e-9)


def test_rectangle_area_exact() -> None:
    geom = rectangle(0.5, 0.5, 0.2, 0.1)
    assert math.isclose(geom.area, 0.02, rel_tol=1e-12)
    assert geom.bounds == (0.4, 0.45, 0.6, 0.55)


def test_obround_horizontal_area() -> None:
    w, h = 0.3, 0.1
    geom = obround(0.0, 0.0, w, h)
    expected = (w - h) * h + math.pi * (h / 2.0) ** 2
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_obround_vertical_area() -> None:
    w, h = 0.1, 0.3
    geom = obround(0.0, 0.0, w, h)
    expected = (h - w) * w + math.pi * (w / 2.0) ** 2
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_obround_square_is_circle() -> None:
    geom = obround(0.0, 0.0, 0.2, 0.2)
    assert math.isclose(geom.area, math.pi * 0.01, rel_tol=5e-3)


def test_regular_polygon_area_exact() -> None:
    n, r = 6, 0.1
    geom = regular_polygon(0.0, 0.0, r, n)
    expected = 0.5 * n * r * r * math.sin(2.0 * math.pi / n)
    assert math.isclose(geom.area, expected, rel_tol=1e-12)


def test_regular_polygon_rotation_moves_first_vertex() -> None:
    geom = regular_polygon(0.0, 0.0, 1.0, 4, rotation_deg=90.0)
    xs, ys = geom.exterior.coords.xy  # type: ignore[attr-defined]
    assert math.isclose(xs[0], 0.0, abs_tol=1e-12)
    assert math.isclose(ys[0], 1.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# Arc sampling
# ---------------------------------------------------------------------------


def test_arc_points_ccw_quarter() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=1.0, start_angle_deg=0.0, end_angle_deg=90.0
    )
    pts = arc_points(arc)
    assert math.isclose(pts[0][0], 1.0, abs_tol=1e-12)
    assert math.isclose(pts[0][1], 0.0, abs_tol=1e-12)
    assert math.isclose(pts[-1][0], 0.0, abs_tol=1e-12)
    assert math.isclose(pts[-1][1], 1.0, abs_tol=1e-12)
    # All samples on the circle.
    for x, y in pts:
        assert math.isclose(math.hypot(x, y), 1.0, rel_tol=1e-12)


def test_arc_points_cw_direction() -> None:
    """CW arcs have end < start; samples must sweep downward in angle."""
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=1.0, start_angle_deg=90.0, end_angle_deg=0.0
    )
    pts = arc_points(arc)
    angles = [math.degrees(math.atan2(y, x)) for x, y in pts]
    assert angles[0] > angles[-1]
    assert math.isclose(angles[0], 90.0, abs_tol=1e-9)
    assert math.isclose(angles[-1], 0.0, abs_tol=1e-9)


def test_arc_points_full_circle() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=45.0, end_angle_deg=405.0
    )
    pts = arc_points(arc)
    assert math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-12)
    assert math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-12)
    assert len(pts) >= 17  # at least the minimum full-circle tessellation


def test_arc_points_small_sweep_minimum_two_segments() -> None:
    arc = ArcSegment(center_x=0.0, center_y=0.0, radius=1.0, start_angle_deg=0.0, end_angle_deg=1.0)
    pts = arc_points(arc)
    assert len(pts) >= 3  # n >= 2 segments -> >= 3 points
