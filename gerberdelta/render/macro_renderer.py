from __future__ import annotations

import math
import warnings

import cairocffi as cairo

from gerberdelta.parse.macro_parser import (
    EvaluatedCircle,
    EvaluatedLineCenter,
    EvaluatedLineVector,
    EvaluatedMoire,
    EvaluatedOutline,
    EvaluatedPolygon,
    EvaluatedThermal,
    evaluate_macro_primitives,
)
from gerberdelta.types import MacroAperture

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def draw_macro_flash(
    ctx: cairo.Context,
    x: float,
    y: float,
    aperture: MacroAperture,
) -> None:
    """Draw a macro aperture flash at world position (x, y).

    Evaluates all primitives in the macro definition and draws each using
    cairocffi path operations.  Primitive exposure 0 -> DEST_OUT (erase);
    exposure 1 -> OPERATOR_OVER (add).  All dimensions are scaled by
    ``aperture.unit_scale``.
    """
    if aperture.macro_def is None:
        return
    try:
        primitives = evaluate_macro_primitives(aperture.macro_def, aperture.params)
    except Exception as exc:
        warnings.warn(
            f"Macro '{aperture.macro_def.name}' evaluation failed: {exc}",
            UserWarning,
            stacklevel=2,
        )
        return

    scale = aperture.unit_scale
    for p in primitives:
        match p:
            case EvaluatedCircle():
                _draw_circle(ctx, x, y, p, scale)
            case EvaluatedLineVector():
                _draw_line_vector(ctx, x, y, p, scale)
            case EvaluatedLineCenter():
                _draw_line_center(ctx, x, y, p, scale)
            case EvaluatedOutline():
                _draw_outline(ctx, x, y, p, scale)
            case EvaluatedPolygon():
                _draw_polygon(ctx, x, y, p, scale)
            case EvaluatedMoire():
                _draw_moire(ctx, x, y, p, scale)
            case EvaluatedThermal():
                _draw_thermal(ctx, x, y, p, scale)


def compute_macro_bounding_radius(aperture: MacroAperture) -> float:
    """Estimate the bounding radius of a macro aperture in world units.

    Returns the maximum reach from the origin across all evaluated primitives,
    multiplied by ``aperture.unit_scale``.  Returns 0.0 if the macro cannot
    be evaluated.
    """
    if aperture.macro_def is None:
        return 0.0
    try:
        primitives = evaluate_macro_primitives(aperture.macro_def, aperture.params)
    except Exception:  # pragma: no cover
        return 0.0

    max_r = 0.0
    for p in primitives:
        r: float = 0.0
        match p:
            case EvaluatedCircle():
                r = math.hypot(p.center_x, p.center_y) + p.diameter / 2.0
            case EvaluatedPolygon():
                r = math.hypot(p.center_x, p.center_y) + p.diameter / 2.0
            case EvaluatedLineVector():
                r = (
                    max(
                        math.hypot(p.start_x, p.start_y),
                        math.hypot(p.end_x, p.end_y),
                    )
                    + p.width / 2.0
                )
            case EvaluatedLineCenter():
                r = math.hypot(p.center_x, p.center_y) + math.hypot(p.width / 2.0, p.height / 2.0)
            case EvaluatedMoire():
                r = math.hypot(p.center_x, p.center_y) + p.outer_diameter / 2.0
            case EvaluatedThermal():
                r = math.hypot(p.center_x, p.center_y) + p.outer_diameter / 2.0
            case EvaluatedOutline():
                verts = p.vertices
                if len(verts) >= 2:
                    r = max(math.hypot(verts[i], verts[i + 1]) for i in range(0, len(verts) - 1, 2))
        if r > max_r:
            max_r = r

    return max_r * aperture.unit_scale


# ---------------------------------------------------------------------------
# Exposure helper
# ---------------------------------------------------------------------------


def _apply_exposure(ctx: cairo.Context, exposure: float) -> None:
    if exposure == 0.0:
        ctx.set_operator(cairo.OPERATOR_DEST_OUT)
    else:
        ctx.set_operator(cairo.OPERATOR_OVER)


# ---------------------------------------------------------------------------
# Per-primitive drawing helpers
# ---------------------------------------------------------------------------


def _draw_circle(ctx: cairo.Context, x: float, y: float, p: EvaluatedCircle, scale: float) -> None:
    cx = x + p.center_x * scale
    cy = y + p.center_y * scale
    r = (p.diameter / 2.0) * scale
    if r <= 0.0:
        return
    ctx.save()
    _apply_exposure(ctx, p.exposure)
    ctx.new_path()
    ctx.arc(cx, cy, r, 0.0, 2.0 * math.pi)
    ctx.fill()
    ctx.restore()


def _draw_line_vector(
    ctx: cairo.Context, x: float, y: float, p: EvaluatedLineVector, scale: float
) -> None:
    """Rotated rectangle spanning start->end with width p.width."""
    sx = x + p.start_x * scale
    sy = y + p.start_y * scale
    ex = x + p.end_x * scale
    ey = y + p.end_y * scale
    w2 = (p.width / 2.0) * scale
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length == 0.0:
        return
    # Perpendicular unit vector scaled to half-width
    nx = -dy / length * w2
    ny = dx / length * w2
    # Overall primitive rotation applied around the flash origin (x, y)
    rot = math.radians(p.rotation)
    cos_r = math.cos(rot)
    sin_r = math.sin(rot)

    def _rot(px: float, py: float) -> tuple[float, float]:
        rx = x + cos_r * (px - x) - sin_r * (py - y)
        ry = y + sin_r * (px - x) + cos_r * (py - y)
        return rx, ry

    corners = [
        _rot(sx + nx, sy + ny),
        _rot(sx - nx, sy - ny),
        _rot(ex - nx, ey - ny),
        _rot(ex + nx, ey + ny),
    ]
    ctx.save()
    _apply_exposure(ctx, p.exposure)
    ctx.new_path()
    ctx.move_to(*corners[0])
    for corner_x, corner_y in corners[1:]:
        ctx.line_to(corner_x, corner_y)
    ctx.close_path()
    ctx.fill()
    ctx.restore()


def _draw_line_center(
    ctx: cairo.Context, x: float, y: float, p: EvaluatedLineCenter, scale: float
) -> None:
    """Centred rectangle, optionally rotated."""
    center_x = x + p.center_x * scale
    center_y = y + p.center_y * scale
    w2 = (p.width / 2.0) * scale
    h2 = (p.height / 2.0) * scale
    ctx.save()
    _apply_exposure(ctx, p.exposure)
    ctx.translate(center_x, center_y)
    ctx.rotate(math.radians(p.rotation))
    ctx.new_path()
    ctx.rectangle(-w2, -h2, p.width * scale, p.height * scale)
    ctx.fill()
    ctx.restore()


def _draw_outline(
    ctx: cairo.Context, x: float, y: float, p: EvaluatedOutline, scale: float
) -> None:
    """Arbitrary polygon from flat vertex list [x0, y0, x1, y1, ...]."""
    if len(p.vertices) < 4:
        return
    verts = [v * scale for v in p.vertices]
    ctx.save()
    _apply_exposure(ctx, p.exposure)
    ctx.translate(x, y)
    ctx.rotate(math.radians(p.rotation))
    ctx.new_path()
    for i in range(0, len(verts) - 1, 2):
        vx, vy = verts[i], verts[i + 1]
        if i == 0:
            ctx.move_to(vx, vy)
        else:
            ctx.line_to(vx, vy)
    ctx.close_path()
    ctx.fill()
    ctx.restore()


def _draw_polygon(
    ctx: cairo.Context, x: float, y: float, p: EvaluatedPolygon, scale: float
) -> None:
    """Regular n-sided polygon."""
    center_x = x + p.center_x * scale
    center_y = y + p.center_y * scale
    r = (p.diameter / 2.0) * scale
    if r <= 0.0 or p.num_vertices < 3:
        return
    rot = math.radians(p.rotation)
    ctx.save()
    _apply_exposure(ctx, p.exposure)
    ctx.new_path()
    for i in range(p.num_vertices):
        angle = rot + 2.0 * math.pi * i / p.num_vertices
        vx = center_x + r * math.cos(angle)
        vy = center_y + r * math.sin(angle)
        if i == 0:
            ctx.move_to(vx, vy)
        else:
            ctx.line_to(vx, vy)
    ctx.close_path()
    ctx.fill()
    ctx.restore()


def _draw_moire(ctx: cairo.Context, x: float, y: float, p: EvaluatedMoire, scale: float) -> None:
    """Concentric rings plus crosshair."""
    cx = x + p.center_x * scale
    cy = y + p.center_y * scale
    outer_r = (p.outer_diameter / 2.0) * scale
    gap = p.ring_gap * scale
    thickness = p.ring_thickness * scale
    rot = math.radians(p.rotation)

    max_rings = p.max_rings if p.max_rings > 0 else 100
    for i in range(max_rings):
        r_outer = outer_r - i * (thickness + gap)
        r_inner = r_outer - thickness
        if r_outer <= 0.0:
            break
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.new_path()
        ctx.arc(cx, cy, r_outer, 0.0, 2.0 * math.pi)
        ctx.fill()
        ctx.restore()
        if r_inner > 0.0:
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_DEST_OUT)
            ctx.new_path()
            ctx.arc(cx, cy, r_inner, 0.0, 2.0 * math.pi)
            ctx.fill()
            ctx.restore()

    # Crosshair: two perpendicular bars
    cl = (p.crosshair_length / 2.0) * scale
    ct = (p.crosshair_thickness / 2.0) * scale
    if cl > 0.0 and ct > 0.0:
        for bar_rot in (rot, rot + math.pi / 2.0):
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_OVER)
            ctx.translate(cx, cy)
            ctx.rotate(bar_rot)
            ctx.new_path()
            ctx.rectangle(-cl, -ct, cl * 2.0, ct * 2.0)
            ctx.fill()
            ctx.restore()


def _draw_thermal(
    ctx: cairo.Context, x: float, y: float, p: EvaluatedThermal, scale: float
) -> None:
    """Annulus (ring) with four rectangular anti-pad gaps."""
    cx = x + p.center_x * scale
    cy = y + p.center_y * scale
    r_outer = (p.outer_diameter / 2.0) * scale
    r_inner = (p.inner_diameter / 2.0) * scale
    gap_w = (p.gap / 2.0) * scale
    rot = math.radians(p.rotation)

    if r_outer <= 0.0:
        return

    # 1. Filled outer circle
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_OVER)
    ctx.new_path()
    ctx.arc(cx, cy, r_outer, 0.0, 2.0 * math.pi)
    ctx.fill()
    ctx.restore()

    # 2. Cut inner circle -> leaves the ring
    if r_inner > 0.0:
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_DEST_OUT)
        ctx.new_path()
        ctx.arc(cx, cy, r_inner, 0.0, 2.0 * math.pi)
        ctx.fill()
        ctx.restore()

    # 3. Cut 4 rectangular gaps at 0deg, 90deg, 180deg, 270deg + rotation
    if gap_w > 0.0:
        for i in range(4):
            angle = rot + i * math.pi / 2.0
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_DEST_OUT)
            ctx.translate(cx, cy)
            ctx.rotate(angle)
            ctx.new_path()
            ctx.rectangle(-r_outer, -gap_w, r_outer * 2.0, gap_w * 2.0)
            ctx.fill()
            ctx.restore()
