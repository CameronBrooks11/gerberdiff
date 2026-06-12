"""Macro aperture geometry: evaluated macro primitives -> shapely.

Mirrors ``render/macro_renderer.py`` primitive-by-primitive, with two
deliberate divergences (geometry follows the Gerber spec where the raster
engine takes compositing shortcuts):

1. **Exposure scope** -- an exposure-0 primitive erases *within the macro
   flash only* (spec), whereas the raster engine's ``DEST_OUT`` erases
   underlying canvas content globally.
2. **Rotation centre** -- primitive rotation is applied to the *whole
   primitive* around the macro origin (spec), whereas the raster engine
   rotates some primitives (21, 5, 6, 7) around their own centre.  The two
   agree in the overwhelmingly common cases (rotation 0 or centre at origin).

A macro that fails to evaluate contributes no geometry and a ``Warning``
diagnostic (matching the renderer's behaviour).
"""

from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from gerberdiff.geometry.primitives import circle, rectangle, regular_polygon
from gerberdiff.parse.macro_parser import (
    EvaluatedCircle,
    EvaluatedLineCenter,
    EvaluatedLineVector,
    EvaluatedMoire,
    EvaluatedOutline,
    EvaluatedPolygon,
    EvaluatedPrimitive,
    EvaluatedThermal,
    evaluate_macro_primitives,
)
from gerberdiff.types import Diagnostic, DiagnosticSeverity, MacroAperture

_EMPTY: BaseGeometry = Polygon()


def macro_flash_geometry(
    aperture: MacroAperture,
    x: float,
    y: float,
) -> tuple[BaseGeometry, list[Diagnostic]]:
    """Expand a macro aperture flash at world position (x, y).

    Returns the composed geometry (possibly empty) and any diagnostics.
    Exposure-on primitives union into the accumulator; exposure-off
    primitives subtract from it (within the macro only).
    """
    if aperture.macro_def is None:
        return _EMPTY, []
    try:
        primitives = evaluate_macro_primitives(aperture.macro_def, aperture.params)
    except Exception as exc:
        return _EMPTY, [
            Diagnostic(
                severity=DiagnosticSeverity.Warning,
                message=f"Macro '{aperture.macro_def.name}' evaluation failed: {exc}",
            )
        ]

    acc: BaseGeometry = _EMPTY
    for p in primitives:
        geom = _primitive_geometry(p)
        if geom is None or geom.is_empty:
            continue
        if _exposure_off(p):
            acc = acc.difference(geom)
        else:
            acc = acc.union(geom)

    if acc.is_empty:
        return _EMPTY, []

    # Macro coords -> world: scale to inches, then translate to the flash.
    scale = aperture.unit_scale
    if scale != 1.0:
        acc = affinity.scale(acc, xfact=scale, yfact=scale, origin=(0, 0))
    return affinity.translate(acc, xoff=x, yoff=y), []


# ---------------------------------------------------------------------------
# Per-primitive geometry (macro-local coordinates, unscaled)
# ---------------------------------------------------------------------------


def _exposure_off(p: EvaluatedPrimitive) -> bool:
    exposure = getattr(p, "exposure", 1.0)
    return bool(exposure == 0.0)


def _rotated(geom: BaseGeometry, rotation_deg: float) -> BaseGeometry:
    """Rotate a primitive around the macro origin (spec semantics)."""
    if rotation_deg == 0.0 or geom.is_empty:
        return geom
    return affinity.rotate(geom, rotation_deg, origin=(0, 0))


def _primitive_geometry(p: EvaluatedPrimitive) -> BaseGeometry | None:
    match p:
        case EvaluatedCircle():
            if p.diameter <= 0.0:
                return None
            return _rotated(circle(p.center_x, p.center_y, p.diameter / 2.0), p.rotation)

        case EvaluatedLineVector():
            return _line_vector(p)

        case EvaluatedLineCenter():
            if p.width <= 0.0 or p.height <= 0.0:
                return None
            return _rotated(rectangle(p.center_x, p.center_y, p.width, p.height), p.rotation)

        case EvaluatedOutline():
            if len(p.vertices) < 6:  # need at least 3 points
                return None
            pts = [(p.vertices[i], p.vertices[i + 1]) for i in range(0, len(p.vertices) - 1, 2)]
            return _rotated(Polygon(pts), p.rotation)

        case EvaluatedPolygon():
            if p.diameter <= 0.0 or p.num_vertices < 3:
                return None
            return _rotated(
                regular_polygon(p.center_x, p.center_y, p.diameter / 2.0, p.num_vertices),
                p.rotation,
            )

        case EvaluatedMoire():
            return _moire(p)

        case EvaluatedThermal():
            return _thermal(p)

    return None  # pragma: no cover -- exhaustive match above


def _line_vector(p: EvaluatedLineVector) -> BaseGeometry | None:
    """Rectangle spanning start->end with the given width."""
    if p.width <= 0.0:
        return None
    dx = p.end_x - p.start_x
    dy = p.end_y - p.start_y
    length = math.hypot(dx, dy)
    if length == 0.0:
        return None
    nx = -dy / length * (p.width / 2.0)
    ny = dx / length * (p.width / 2.0)
    quad = Polygon(
        [
            (p.start_x + nx, p.start_y + ny),
            (p.start_x - nx, p.start_y - ny),
            (p.end_x - nx, p.end_y - ny),
            (p.end_x + nx, p.end_y + ny),
        ]
    )
    return _rotated(quad, p.rotation)


def _moire(p: EvaluatedMoire) -> BaseGeometry | None:
    """Concentric rings plus a two-bar crosshair."""
    outer_r = p.outer_diameter / 2.0
    if outer_r <= 0.0:
        return None

    acc: BaseGeometry = _EMPTY
    max_rings = p.max_rings if p.max_rings > 0 else 100
    for i in range(max_rings):
        r_outer = outer_r - i * (p.ring_thickness + p.ring_gap)
        if r_outer <= 0.0:
            break
        ring: BaseGeometry = circle(p.center_x, p.center_y, r_outer)
        r_inner = r_outer - p.ring_thickness
        if r_inner > 0.0:
            ring = ring.difference(circle(p.center_x, p.center_y, r_inner))
        acc = acc.union(ring)

    cl = p.crosshair_length / 2.0
    ct = p.crosshair_thickness / 2.0
    if cl > 0.0 and ct > 0.0:
        h_bar = rectangle(p.center_x, p.center_y, cl * 2.0, ct * 2.0)
        v_bar = rectangle(p.center_x, p.center_y, ct * 2.0, cl * 2.0)
        acc = acc.union(h_bar).union(v_bar)

    if acc.is_empty:
        return None
    return _rotated(acc, p.rotation)


def _thermal(p: EvaluatedThermal) -> BaseGeometry | None:
    """Annulus with four rectangular gaps at 0/90/180/270 degrees."""
    r_outer = p.outer_diameter / 2.0
    if r_outer <= 0.0:
        return None

    acc: BaseGeometry = circle(p.center_x, p.center_y, r_outer)
    r_inner = p.inner_diameter / 2.0
    if r_inner > 0.0:
        acc = acc.difference(circle(p.center_x, p.center_y, r_inner))

    gap_w = p.gap / 2.0
    if gap_w > 0.0:
        # Bars need only span the annulus (2*r_outer); oversizing to 4*r_outer
        # avoids exact edge-tangency in the boolean difference.
        h_gap = rectangle(p.center_x, p.center_y, r_outer * 4.0, gap_w * 2.0)
        v_gap = rectangle(p.center_x, p.center_y, gap_w * 2.0, r_outer * 4.0)
        acc = acc.difference(h_gap).difference(v_gap)

    if acc.is_empty:
        return None
    return _rotated(acc, p.rotation)
