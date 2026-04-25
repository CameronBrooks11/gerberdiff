from __future__ import annotations

import math

from gerberdiff.types import ArcSegment, BoundingBox

_RAD_TO_DEG = 180.0 / math.pi


def compute_arc_multi_quadrant(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    i: float,
    j: float,
    clockwise: bool,
) -> ArcSegment | None:
    """Compute arc geometry for G75 (multi-quadrant) mode.

    (i, j) are signed offsets from the start point to the arc centre.
    The arc can sweep any angle up to 360deg.

    Returns None for a degenerate arc (radius < 1e-10).
    """
    center_x = start_x + i
    center_y = start_y + j
    radius = math.hypot(start_x - center_x, start_y - center_y)

    if radius < 1e-10:
        return None

    start_angle = math.atan2(start_y - center_y, start_x - center_x) * _RAD_TO_DEG
    end_angle = math.atan2(end_y - center_y, end_x - center_x) * _RAD_TO_DEG

    # Full-circle: start and end coincide
    if math.hypot(start_x - end_x, start_y - end_y) < 1e-10:
        end_angle = start_angle - 360.0 if clockwise else start_angle + 360.0
    else:
        if clockwise and end_angle >= start_angle:
            end_angle -= 360.0
        elif not clockwise and end_angle <= start_angle:
            end_angle += 360.0

    return ArcSegment(
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        start_angle_deg=start_angle,
        end_angle_deg=end_angle,
    )


def compute_arc_single_quadrant(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    i: float,
    j: float,
    clockwise: bool,
) -> ArcSegment | None:
    """Compute arc geometry for G74 (single-quadrant) mode.

    In G74 mode the magnitude of (i, j) is always positive but the sign is
    implicit.  Try all four sign combinations and keep the candidate where the
    arc sweep is <= 90deg (single-quadrant constraint), preferring the one with
    the smallest start-to-end radius mismatch.

    Returns None if no valid candidate is found.
    """
    abs_i = abs(i)
    abs_j = abs(j)

    best: ArcSegment | None = None
    best_error = math.inf

    for sign_i, sign_j in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        cx = start_x + sign_i * abs_i
        cy = start_y + sign_j * abs_j

        r_start = math.hypot(start_x - cx, start_y - cy)
        if r_start < 1e-10:
            continue
        r_end = math.hypot(end_x - cx, end_y - cy)

        # Normalise angles to [0, 360)
        sa = math.atan2(start_y - cy, start_x - cx) * _RAD_TO_DEG % 360.0
        ea = math.atan2(end_y - cy, end_x - cx) * _RAD_TO_DEG % 360.0

        # Compute the arc sweep in the intended direction
        if clockwise:
            sweep = sa - ea
            if sweep <= 0:
                sweep += 360.0
        else:
            sweep = ea - sa
            if sweep <= 0:
                sweep += 360.0

        # G74 constraint: arc must stay within a single quadrant (<= 90deg)
        if sweep > 90.5:
            continue

        error = abs(r_start - r_end)
        if error < best_error:
            best_error = error
            # Full-circle degenerate case
            if math.hypot(start_x - end_x, start_y - end_y) < 1e-10:
                end_a = sa - 360.0 if clockwise else sa + 360.0
            else:
                end_a = ea
            best = ArcSegment(
                center_x=cx,
                center_y=cy,
                radius=r_start,
                start_angle_deg=sa,
                end_angle_deg=end_a,
            )

    return best


def arc_bounding_box(arc: ArcSegment, aperture_radius: float = 0.0) -> BoundingBox:
    """Return the axis-aligned bounding box of an arc segment.

    Correctly handles multi-quadrant arcs by checking whether any of the four
    axis-extrema angles (0, 90, 180, 270 degrees) fall within the swept range.

    *aperture_radius* is added as padding on all sides (half the trace width).
    """
    bb = BoundingBox()
    cx, cy, r = arc.center_x, arc.center_y, arc.radius

    # Expand by both endpoints.
    for theta_deg in (arc.start_angle_deg, arc.end_angle_deg):
        theta_rad = math.radians(theta_deg)
        bb.expand(cx + r * math.cos(theta_rad), cy + r * math.sin(theta_rad), aperture_radius)

    # Determine the angular range covered by the arc.  The ArcSegment convention
    # (set by compute_arc_multi_quadrant / compute_arc_single_quadrant) is:
    #   CCW arcs: end_angle_deg > start_angle_deg
    #   CW arcs:  end_angle_deg < start_angle_deg
    # So [lo, hi] = [min, max] covers the swept interval regardless of direction.
    lo = min(arc.start_angle_deg, arc.end_angle_deg)
    hi = max(arc.start_angle_deg, arc.end_angle_deg)

    # For each axis extremum (0°, 90°, 180°, 270°), check whether any integer
    # multiple of 360° shifted copy of that angle falls in [lo, hi].  If so,
    # the arc passes through that extremum and we must expand the bbox.
    for axis_angle in (0.0, 90.0, 180.0, 270.0):
        k_start = math.ceil((lo - axis_angle) / 360.0)
        for k in range(k_start, k_start + 4):
            candidate = axis_angle + 360.0 * k
            if lo <= candidate <= hi:
                theta_rad = math.radians(axis_angle)
                bb.expand(
                    cx + r * math.cos(theta_rad), cy + r * math.sin(theta_rad), aperture_radius
                )
                break

    return bb
