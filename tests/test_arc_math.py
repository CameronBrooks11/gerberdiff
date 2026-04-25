from __future__ import annotations

import math

from gerberdiff.parse.arc_math import (
    arc_bounding_box,
    compute_arc_multi_quadrant,
    compute_arc_single_quadrant,
)


def test_multi_quadrant_quarter_circle_ccw() -> None:
    # Arc from (1,0) to (0,1) CCW; center (0,0): I=-1, J=0
    arc = compute_arc_multi_quadrant(1.0, 0.0, 0.0, 1.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    assert abs(arc.center_x) < 1e-9
    assert abs(arc.center_y) < 1e-9
    assert abs(arc.radius - 1.0) < 1e-9
    assert abs(arc.start_angle_deg - 0.0) < 1e-6
    assert abs(arc.end_angle_deg - 90.0) < 1e-6


def test_multi_quadrant_quarter_circle_cw() -> None:
    # Arc from (0,1) to (1,0) CW; center (0,0): I=0, J=-1
    arc = compute_arc_multi_quadrant(0.0, 1.0, 1.0, 0.0, 0.0, -1.0, clockwise=True)
    assert arc is not None
    assert abs(arc.radius - 1.0) < 1e-9
    # CW: end_angle < start_angle
    assert arc.end_angle_deg < arc.start_angle_deg


def test_multi_quadrant_full_circle_ccw() -> None:
    # start == end, non-zero I -> full 360deg arc
    arc = compute_arc_multi_quadrant(1.0, 0.0, 1.0, 0.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    assert abs(arc.end_angle_deg - arc.start_angle_deg - 360.0) < 1e-6


def test_multi_quadrant_full_circle_cw() -> None:
    arc = compute_arc_multi_quadrant(1.0, 0.0, 1.0, 0.0, -1.0, 0.0, clockwise=True)
    assert arc is not None
    assert abs(arc.start_angle_deg - arc.end_angle_deg - 360.0) < 1e-6


def test_multi_quadrant_degenerate_returns_none() -> None:
    # i=j=0 -> radius 0 -> degenerate
    arc = compute_arc_multi_quadrant(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, clockwise=False)
    assert arc is None


def test_multi_quadrant_radius_consistency() -> None:
    # Both start and end should be on the circle
    arc = compute_arc_multi_quadrant(2.0, 0.0, 0.0, 2.0, -2.0, 0.0, clockwise=False)
    assert arc is not None
    r_start = math.hypot(2.0 - arc.center_x, 0.0 - arc.center_y)
    r_end = math.hypot(0.0 - arc.center_x, 2.0 - arc.center_y)
    assert abs(r_start - arc.radius) < 1e-9
    assert abs(r_end - arc.radius) < 1e-9


def test_single_quadrant_quarter_circle() -> None:
    # Same geometry as multi-quadrant test: pick i=1,j=0 gives center (-1+1=0, 0+0=0) hmm
    # Arc from (1,0) to (0,1) CCW; abs_i=1, abs_j=0
    arc = compute_arc_single_quadrant(1.0, 0.0, 0.0, 1.0, 1.0, 0.0, clockwise=False)
    assert arc is not None
    assert abs(arc.radius - 1.0) < 1e-9
    # sweep should be <= 90deg
    sweep = arc.end_angle_deg - arc.start_angle_deg
    assert 0.0 < sweep <= 90.5


def test_single_quadrant_degenerate_returns_none() -> None:
    arc = compute_arc_single_quadrant(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, clockwise=False)
    assert arc is None


# ---------------------------------------------------------------------------
# arc_bounding_box tests
# ---------------------------------------------------------------------------


def test_arc_bounding_box_half_circle_extends_beyond_chord() -> None:
    # CCW 180° arc from (1,0) to (-1,0), centre (0,0), radius 1.
    # The top of the arc is at (0, 1); the chord midpoint is at (0, 0).
    arc = compute_arc_multi_quadrant(1.0, 0.0, -1.0, 0.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    bb = arc_bounding_box(arc)
    assert bb.max_y > 0.99, f"expected max_y≈1.0, got {bb.max_y}"
    assert bb.min_y < 0.01, f"expected min_y≈0, got {bb.min_y} (arc doesn't dip below chord)"
    # The arc does NOT sweep through 270° (bottom), so min_y must stay at 0.
    assert bb.min_y >= -0.01, "arc should not extend below y=0"


def test_arc_bounding_box_full_circle_equals_diameter() -> None:
    # Full circle: radius 1, centre (0,0).  Bbox must be [-1, -1] to [1, 1].
    arc = compute_arc_multi_quadrant(1.0, 0.0, 1.0, 0.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    bb = arc_bounding_box(arc)
    assert abs(bb.max_x - 1.0) < 1e-6
    assert abs(bb.min_x - (-1.0)) < 1e-6
    assert abs(bb.max_y - 1.0) < 1e-6
    assert abs(bb.min_y - (-1.0)) < 1e-6


def test_arc_bounding_box_quarter_circle_covers_axis_extremum() -> None:
    # CCW quarter arc from (1,0) to (0,1), centre (0,0).
    # The arc sweeps 0°→90° so only the 90° extremum (0,1) is hit, which is
    # already an endpoint.  The 0° extremum (1,0) is the start endpoint.
    # Neither 180° nor 270° is in the range, so bbox = [(0,0), (1,1)].
    arc = compute_arc_multi_quadrant(1.0, 0.0, 0.0, 1.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    bb = arc_bounding_box(arc)
    assert abs(bb.max_x - 1.0) < 1e-6
    assert abs(bb.max_y - 1.0) < 1e-6
    assert bb.min_x >= -1e-9
    assert bb.min_y >= -1e-9


def test_arc_bounding_box_aperture_radius_padding() -> None:
    # Full circle with aperture radius 0.1 → bbox should be [-1.1, -1.1] to [1.1, 1.1].
    arc = compute_arc_multi_quadrant(1.0, 0.0, 1.0, 0.0, -1.0, 0.0, clockwise=False)
    assert arc is not None
    bb = arc_bounding_box(arc, aperture_radius=0.1)
    assert abs(bb.max_x - 1.1) < 1e-6
    assert abs(bb.min_x - (-1.1)) < 1e-6
