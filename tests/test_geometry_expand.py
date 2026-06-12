"""Tests for geometry/expand.py: flash, stroke, and region expansion."""

from __future__ import annotations

import itertools
import math

from gerberdiff.geometry.expand import flash_geometry, region_geometry, stroke_geometry
from gerberdiff.types import (
    ApertureState,
    ArcSegment,
    BlockAperture,
    CircleAperture,
    DiagnosticSeverity,
    DrawOp,
    InterpolationMode,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
    RegionFill,
)


def _op(
    *,
    start: tuple[float, float] = (0.0, 0.0),
    stop: tuple[float, float] = (0.0, 0.0),
    state: ApertureState = ApertureState.Flash,
    arc: ArcSegment | None = None,
) -> DrawOp:
    return DrawOp(
        start_x=start[0],
        start_y=start[1],
        stop_x=stop[0],
        stop_y=stop[1],
        aperture_index=10,
        aperture_state=state,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
        arc_segment=arc,
    )


# ---------------------------------------------------------------------------
# Flashes
# ---------------------------------------------------------------------------


def test_circle_flash_area_and_position() -> None:
    geom, diags = flash_geometry(_op(stop=(1.0, 2.0)), CircleAperture(diameter=0.1))
    assert not diags
    assert math.isclose(geom.area, math.pi * 0.05**2, rel_tol=5e-3)
    assert math.isclose(geom.centroid.x, 1.0, abs_tol=1e-9)
    assert math.isclose(geom.centroid.y, 2.0, abs_tol=1e-9)


def test_rectangle_flash_exact_area() -> None:
    geom, _ = flash_geometry(_op(), RectangleAperture(width=0.2, height=0.05))
    assert math.isclose(geom.area, 0.01, rel_tol=1e-12)


def test_obround_flash_area() -> None:
    geom, _ = flash_geometry(_op(), ObroundAperture(width=0.2, height=0.1))
    expected = 0.1 * 0.1 + math.pi * 0.05**2
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_polygon_flash_area() -> None:
    geom, _ = flash_geometry(_op(), PolygonAperture(outer_diameter=0.2, num_vertices=8))
    expected = 0.5 * 8 * 0.1**2 * math.sin(2.0 * math.pi / 8)
    assert math.isclose(geom.area, expected, rel_tol=1e-12)


def test_holed_flash_is_annulus() -> None:
    ap = CircleAperture(diameter=0.1, hole_diameter=0.04)
    geom, _ = flash_geometry(_op(), ap)
    expected = math.pi * (0.05**2 - 0.02**2)
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_zero_diameter_flash_empty() -> None:
    geom, _ = flash_geometry(_op(), CircleAperture(diameter=0.0))
    assert geom.is_empty


def test_none_aperture_flash_empty() -> None:
    geom, _ = flash_geometry(_op(), None)
    assert geom.is_empty


def test_block_aperture_flash_empty_here() -> None:
    """Blocks are flattened by layer_geometry, not expanded here."""
    geom, _ = flash_geometry(_op(), BlockAperture())
    assert geom.is_empty


# ---------------------------------------------------------------------------
# Linear strokes
# ---------------------------------------------------------------------------


def test_round_stroke_is_capsule() -> None:
    op = _op(start=(0.0, 0.0), stop=(0.5, 0.0), state=ApertureState.On)
    geom, _ = stroke_geometry(op, CircleAperture(diameter=0.1))
    expected = 0.5 * 0.1 + math.pi * 0.05**2
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_rect_stroke_axis_aligned_exact_minkowski() -> None:
    """Segment of length L along X swept with a w x h rect = (L+w) x h rect."""
    op = _op(start=(0.0, 0.0), stop=(0.4, 0.0), state=ApertureState.On)
    geom, _ = stroke_geometry(op, RectangleAperture(width=0.1, height=0.05))
    assert math.isclose(geom.area, (0.4 + 0.1) * 0.05, rel_tol=1e-12)
    assert geom.bounds == (-0.05, -0.025, 0.45, 0.025)


def test_rect_stroke_diagonal_is_convex_hull() -> None:
    """Diagonal sweep: area = rect + L * (projected width), via hull."""
    op = _op(start=(0.0, 0.0), stop=(0.3, 0.3), state=ApertureState.On)
    geom, _ = stroke_geometry(op, RectangleAperture(width=0.1, height=0.1))
    # Minkowski area for convex S and segment v: area(S) + |cross-section| * |v|
    # For a square of side s swept at 45 deg: width across direction = s*sqrt(2)
    length = math.hypot(0.3, 0.3)
    expected = 0.1 * 0.1 + length * 0.1 * math.sqrt(2.0)
    assert math.isclose(geom.area, expected, rel_tol=1e-9)


def test_degenerate_stroke_is_aperture_shape() -> None:
    op = _op(start=(0.1, 0.1), stop=(0.1, 0.1), state=ApertureState.On)
    geom, _ = stroke_geometry(op, CircleAperture(diameter=0.08))
    assert math.isclose(geom.area, math.pi * 0.04**2, rel_tol=5e-3)

    geom2, _ = stroke_geometry(op, RectangleAperture(width=0.06, height=0.02))
    assert math.isclose(geom2.area, 0.0012, rel_tol=1e-12)


def test_none_aperture_stroke_empty() -> None:
    op = _op(start=(0.0, 0.0), stop=(1.0, 0.0), state=ApertureState.On)
    geom, _ = stroke_geometry(op, None)
    assert geom.is_empty


# ---------------------------------------------------------------------------
# Arc strokes
# ---------------------------------------------------------------------------


def test_round_arc_stroke_area() -> None:
    """Quarter arc radius R with round brush d: area ~ arc_len*d + cap circle."""
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=0.0, end_angle_deg=90.0
    )
    op = _op(start=(0.5, 0.0), stop=(0.0, 0.5), state=ApertureState.On, arc=arc)
    geom, diags = stroke_geometry(op, CircleAperture(diameter=0.05))
    assert not diags
    arc_len = math.pi * 0.5 / 2.0
    expected = arc_len * 0.05 + math.pi * 0.025**2
    assert math.isclose(geom.area, expected, rel_tol=0.01)


def test_nonround_arc_stroke_falls_back_with_info() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=0.0, end_angle_deg=90.0
    )
    op = _op(start=(0.5, 0.0), stop=(0.0, 0.5), state=ApertureState.On, arc=arc)
    geom, diags = stroke_geometry(op, RectangleAperture(width=0.04, height=0.02))
    assert not geom.is_empty
    assert len(diags) == 1
    assert diags[0].severity == DiagnosticSeverity.Info
    assert "approximated" in diags[0].message


# ---------------------------------------------------------------------------
# Region fills
# ---------------------------------------------------------------------------


def _region_square(x0: float, y0: float, side: float) -> list[DrawOp]:
    """Off-move to corner then four On segments tracing a square."""
    pts = [
        (x0, y0),
        (x0 + side, y0),
        (x0 + side, y0 + side),
        (x0, y0 + side),
        (x0, y0),
    ]
    ops = [_op(stop=pts[0], state=ApertureState.Off)]
    for prev, nxt in itertools.pairwise(pts):
        ops.append(_op(start=prev, stop=nxt, state=ApertureState.On))
    return ops


def test_region_square_area() -> None:
    rf = RegionFill(layer_index=0, net_state_index=0, segments=_region_square(0.0, 0.0, 1.0))
    geom, diags = region_geometry(rf)
    assert not diags
    assert math.isclose(geom.area, 1.0, rel_tol=1e-12)


def test_region_even_odd_hole() -> None:
    """Outer square + inner square contour = frame (even-odd fill)."""
    segments = _region_square(0.0, 0.0, 1.0) + _region_square(0.25, 0.25, 0.5)
    rf = RegionFill(layer_index=0, net_state_index=0, segments=segments)
    geom, _ = region_geometry(rf)
    assert math.isclose(geom.area, 1.0 - 0.25, rel_tol=1e-12)


def test_region_with_arc_segment() -> None:
    """Half-disc: straight diameter then a CCW arc closing over the top."""
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=1.0, start_angle_deg=0.0, end_angle_deg=180.0
    )
    segments = [
        _op(stop=(-1.0, 0.0), state=ApertureState.Off),
        _op(start=(-1.0, 0.0), stop=(1.0, 0.0), state=ApertureState.On),
        _op(start=(1.0, 0.0), stop=(-1.0, 0.0), state=ApertureState.On, arc=arc),
    ]
    rf = RegionFill(layer_index=0, net_state_index=0, segments=segments)
    geom, _ = region_geometry(rf)
    assert math.isclose(geom.area, math.pi / 2.0, rel_tol=5e-3)


def test_region_empty_segments() -> None:
    rf = RegionFill(layer_index=0, net_state_index=0, segments=[])
    geom, _ = region_geometry(rf)
    assert geom.is_empty


def test_region_degenerate_two_points() -> None:
    segments = [
        _op(stop=(0.0, 0.0), state=ApertureState.Off),
        _op(start=(0.0, 0.0), stop=(1.0, 0.0), state=ApertureState.On),
    ]
    rf = RegionFill(layer_index=0, net_state_index=0, segments=segments)
    geom, _ = region_geometry(rf)
    assert geom.is_empty


def test_region_without_leading_off() -> None:
    """First contour may start with an On segment (uses its start point)."""
    pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    segments = [
        _op(start=prev, stop=nxt, state=ApertureState.On) for prev, nxt in itertools.pairwise(pts)
    ]
    rf = RegionFill(layer_index=0, net_state_index=0, segments=segments)
    geom, _ = region_geometry(rf)
    assert math.isclose(geom.area, 1.0, rel_tol=1e-12)
