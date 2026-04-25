from __future__ import annotations

import math

import cairocffi as cairo

from gerberdelta.types import (
    Aperture,
    ApertureState,
    ArcSegment,
    BlockAperture,
    CircleAperture,
    DrawOp,
    InterpolationMode,
    MacroAperture,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
)

# ---------------------------------------------------------------------------
# Arc
# ---------------------------------------------------------------------------


def draw_arc_path(ctx: cairo.Context, arc: ArcSegment, clockwise: bool) -> None:
    """Add an arc to the current path without stroking or filling.

    Gerber clockwise arcs map to cairo's ``arc_negative`` because cairo
    angles increase counter-clockwise.
    """
    start_rad = math.radians(arc.start_angle_deg)
    end_rad = math.radians(arc.end_angle_deg)
    if clockwise:
        ctx.arc_negative(arc.center_x, arc.center_y, arc.radius, start_rad, end_rad)
    else:
        ctx.arc(arc.center_x, arc.center_y, arc.radius, start_rad, end_rad)


# ---------------------------------------------------------------------------
# Region segments
# ---------------------------------------------------------------------------


def draw_net_segment_in_region(ctx: cairo.Context, net: DrawOp) -> None:
    """Add one net to the current region path (inside a G36..G37 block).

    ``ApertureState.Off`` starts a new contour; arcs use :func:`draw_arc_path`;
    linear moves become ``line_to``.
    """
    if net.aperture_state == ApertureState.Off:
        ctx.move_to(net.stop_x, net.stop_y)
    elif net.arc_segment is not None:
        draw_arc_path(
            ctx,
            net.arc_segment,
            net.interpolation == InterpolationMode.ClockwiseCircular,
        )
    else:
        ctx.line_to(net.stop_x, net.stop_y)


# ---------------------------------------------------------------------------
# Stroke
# ---------------------------------------------------------------------------


def draw_net_as_stroke(ctx: cairo.Context, net: DrawOp, aperture: Aperture | None) -> None:
    """Stroke a single ``On``-state net using the aperture's line width."""
    if aperture is None:
        return

    match aperture:
        case CircleAperture():
            ctx.set_line_width(aperture.diameter)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        case RectangleAperture():
            ctx.set_line_width(min(aperture.width, aperture.height))
            ctx.set_line_cap(cairo.LINE_CAP_SQUARE)
        case ObroundAperture():
            ctx.set_line_width(min(aperture.width, aperture.height))
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        case PolygonAperture():
            ctx.set_line_width(aperture.outer_diameter)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        case _:
            ctx.set_line_width(0.001)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)

    ctx.new_path()
    ctx.move_to(net.start_x, net.start_y)
    if net.arc_segment is not None:
        draw_arc_path(
            ctx,
            net.arc_segment,
            net.interpolation == InterpolationMode.ClockwiseCircular,
        )
    else:
        ctx.line_to(net.stop_x, net.stop_y)
    ctx.stroke()


# ---------------------------------------------------------------------------
# Flash
# ---------------------------------------------------------------------------


def draw_flash(ctx: cairo.Context, net: DrawOp, aperture: Aperture | None) -> None:
    """Draw a flash (D03) at ``net.stop_x``, ``net.stop_y``.

    Macro and Block apertures are handled by the renderer directly
    (``macro_renderer`` / block render pass) so they are silently skipped here.
    """
    if aperture is None:
        return

    x, y = net.stop_x, net.stop_y
    match aperture:
        case CircleAperture():
            _draw_circle_flash(ctx, x, y, aperture)
        case RectangleAperture():
            _draw_rectangle_flash(ctx, x, y, aperture)
        case ObroundAperture():
            _draw_obround_flash(ctx, x, y, aperture)
        case PolygonAperture():
            _draw_polygon_flash(ctx, x, y, aperture)
        case MacroAperture() | BlockAperture():
            pass  # deferred to renderer


# ---------------------------------------------------------------------------
# Private helpers -- each takes a concrete aperture type for mypy narrowing
# ---------------------------------------------------------------------------


def _draw_hole(ctx: cairo.Context, x: float, y: float, hole_diameter: float) -> None:
    """Punch a circular hole using DEST_OUT compositing."""
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_DEST_OUT)
    ctx.new_path()
    ctx.arc(x, y, hole_diameter / 2.0, 0.0, 2.0 * math.pi)
    ctx.fill()
    ctx.restore()


def _draw_circle_flash(ctx: cairo.Context, x: float, y: float, ap: CircleAperture) -> None:
    ctx.new_path()
    ctx.arc(x, y, ap.diameter / 2.0, 0.0, 2.0 * math.pi)
    ctx.fill()
    if ap.hole_diameter is not None:
        _draw_hole(ctx, x, y, ap.hole_diameter)


def _draw_rectangle_flash(ctx: cairo.Context, x: float, y: float, ap: RectangleAperture) -> None:
    w2, h2 = ap.width / 2.0, ap.height / 2.0
    ctx.new_path()
    ctx.rectangle(x - w2, y - h2, ap.width, ap.height)
    ctx.fill()
    if ap.hole_diameter is not None:
        _draw_hole(ctx, x, y, ap.hole_diameter)


def _draw_obround_flash(ctx: cairo.Context, x: float, y: float, ap: ObroundAperture) -> None:
    """Obround: rectangle with semicircular ends on the short axis."""
    w, h = ap.width, ap.height
    r = min(w, h) / 2.0
    w2, h2 = w / 2.0, h / 2.0
    ctx.new_path()
    if w >= h:
        # Horizontal obround
        ctx.arc(x + w2 - r, y, r, -math.pi / 2.0, math.pi / 2.0)
        ctx.arc(x - w2 + r, y, r, math.pi / 2.0, 3.0 * math.pi / 2.0)
    else:
        # Vertical obround
        ctx.arc(x, y + h2 - r, r, 0.0, math.pi)
        ctx.arc(x, y - h2 + r, r, math.pi, 2.0 * math.pi)
    ctx.close_path()
    ctx.fill()
    if ap.hole_diameter is not None:
        _draw_hole(ctx, x, y, ap.hole_diameter)


def _draw_polygon_flash(ctx: cairo.Context, x: float, y: float, ap: PolygonAperture) -> None:
    r = ap.outer_diameter / 2.0
    n = ap.num_vertices
    rot = math.radians(ap.rotation)
    ctx.new_path()
    for i in range(n):
        angle = rot + 2.0 * math.pi * i / n
        px = x + r * math.cos(angle)
        py = y + r * math.sin(angle)
        if i == 0:
            ctx.move_to(px, py)
        else:
            ctx.line_to(px, py)
    ctx.close_path()
    ctx.fill()
    if ap.hole_diameter is not None:
        _draw_hole(ctx, x, y, ap.hole_diameter)
