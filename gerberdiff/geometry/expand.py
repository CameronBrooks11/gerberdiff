"""Expand individual IR draw operations into shapely geometry.

Each function returns ``(geometry, diagnostics)``.  Geometry is in the
operation's own coordinate space (inches); layer transforms and
step-and-repeat are applied later by ``layer_geometry``.

Fidelity notes
--------------
- Round-aperture strokes are exact (capsule = ``LineString.buffer``).
- Non-round convex apertures on **linear** strokes are exact: the Minkowski
  sum of a segment with a convex shape is the convex hull of the shape placed
  at both endpoints.
- Non-round apertures on **arc** strokes fall back to a round brush of
  radius ``max(w, h) / 2`` with an Info diagnostic (matches the raster
  engine's documented approximation for that case).
- Aperture holes are subtracted from the flash shape only.  They do *not*
  erase underlying image content (Gerber spec semantics; the raster engine's
  ``DEST_OUT`` punch is a known compositing shortcut).
"""

from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from gerberdiff.geometry.macro_geom import macro_flash_geometry
from gerberdiff.geometry.primitives import (
    arc_points,
    circle,
    obround,
    rectangle,
    regular_polygon,
)
from gerberdiff.types import (
    Aperture,
    ApertureState,
    BlockAperture,
    CircleAperture,
    Diagnostic,
    DiagnosticSeverity,
    DrawOp,
    MacroAperture,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
    RegionFill,
)

_EMPTY: BaseGeometry = Polygon()
_NO_DIAGS: list[Diagnostic] = []


# ---------------------------------------------------------------------------
# Simple aperture outline (shared by flash and stroke expansion)
# ---------------------------------------------------------------------------


def _aperture_outline(ap: Aperture, x: float, y: float) -> BaseGeometry | None:
    """The filled outline of a simple aperture centred at (x, y), no hole."""
    match ap:
        case CircleAperture():
            if ap.diameter <= 0.0:
                return None
            return circle(x, y, ap.diameter / 2.0)
        case RectangleAperture():
            if ap.width <= 0.0 or ap.height <= 0.0:
                return None
            return rectangle(x, y, ap.width, ap.height)
        case ObroundAperture():
            if ap.width <= 0.0 or ap.height <= 0.0:
                return None
            return obround(x, y, ap.width, ap.height)
        case PolygonAperture():
            if ap.outer_diameter <= 0.0 or ap.num_vertices < 3:
                return None
            return regular_polygon(x, y, ap.outer_diameter / 2.0, ap.num_vertices, ap.rotation)
    return None


# ---------------------------------------------------------------------------
# Flash (D03)
# ---------------------------------------------------------------------------


def flash_geometry(
    op: DrawOp,
    ap: Aperture | None,
) -> tuple[BaseGeometry, list[Diagnostic]]:
    """Expand a flash at ``(op.stop_x, op.stop_y)``.

    Block apertures are handled by ``layer_geometry`` (they flatten into the
    replay sequence); passing one here returns empty geometry.
    """
    if ap is None or isinstance(ap, BlockAperture):
        return _EMPTY, _NO_DIAGS

    x, y = op.stop_x, op.stop_y

    if isinstance(ap, MacroAperture):
        return macro_flash_geometry(ap, x, y)

    shape = _aperture_outline(ap, x, y)
    if shape is None:
        return _EMPTY, _NO_DIAGS

    hole = ap.hole_diameter
    if hole is not None and hole > 0.0:
        shape = shape.difference(circle(x, y, hole / 2.0))
    return shape, _NO_DIAGS


# ---------------------------------------------------------------------------
# Stroke (D01)
# ---------------------------------------------------------------------------


def stroke_geometry(
    op: DrawOp,
    ap: Aperture | None,
) -> tuple[BaseGeometry, list[Diagnostic]]:
    """Expand a D01 stroke (linear or arc) into its swept filled shape."""
    if ap is None:
        return _EMPTY, _NO_DIAGS

    if op.arc_segment is not None:
        return _arc_stroke(op, ap)
    return _linear_stroke(op, ap)


def _linear_stroke(op: DrawOp, ap: Aperture) -> tuple[BaseGeometry, list[Diagnostic]]:
    start = (op.start_x, op.start_y)
    stop = (op.stop_x, op.stop_y)
    degenerate = start == stop

    if isinstance(ap, CircleAperture):
        if ap.diameter <= 0.0:
            return _EMPTY, _NO_DIAGS
        r = ap.diameter / 2.0
        if degenerate:
            return circle(*stop, r), _NO_DIAGS
        return LineString([start, stop]).buffer(r), _NO_DIAGS

    # Convex non-round aperture: exact Minkowski sum for a linear segment is
    # the convex hull of the aperture placed at both endpoints.
    shape_a = _aperture_outline(ap, *start)
    if shape_a is None:
        return _EMPTY, _NO_DIAGS
    if degenerate:
        return shape_a, _NO_DIAGS
    shape_b = _aperture_outline(ap, *stop)
    assert shape_b is not None  # same aperture, same validity
    return unary_union([shape_a, shape_b]).convex_hull, _NO_DIAGS


def _arc_stroke(op: DrawOp, ap: Aperture) -> tuple[BaseGeometry, list[Diagnostic]]:
    arc = op.arc_segment
    assert arc is not None
    pts = arc_points(arc)

    if isinstance(ap, CircleAperture):
        if ap.diameter <= 0.0:
            return _EMPTY, _NO_DIAGS
        return LineString(pts).buffer(ap.diameter / 2.0), _NO_DIAGS

    # Non-round aperture swept along an arc: approximate with a round brush.
    width = _stroke_fallback_width(ap)
    if width <= 0.0:
        return _EMPTY, _NO_DIAGS
    diag = Diagnostic(
        severity=DiagnosticSeverity.Info,
        message=(
            f"arc stroke with {type(ap).__name__} approximated by a round "
            f"brush of diameter {width:.6f} in"
        ),
    )
    return LineString(pts).buffer(width / 2.0), [diag]


def _stroke_fallback_width(ap: Aperture) -> float:
    """Brush width for non-round arc strokes (mirrors the raster engine)."""
    match ap:
        case RectangleAperture() | ObroundAperture():
            return max(ap.width, ap.height)
        case PolygonAperture():
            return ap.outer_diameter
        case _:
            return 0.0


# ---------------------------------------------------------------------------
# Region fill (G36/G37)
# ---------------------------------------------------------------------------


def region_geometry(region: RegionFill) -> tuple[BaseGeometry, list[Diagnostic]]:
    """Expand a region fill into polygon geometry.

    Contours are split on ``Off`` (D02 move) segments; arcs are sampled at
    chord tolerance.  Multiple contours combine with even-odd semantics
    (matching the renderer's ``FILL_RULE_EVEN_ODD``).
    """
    contours: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    for seg in region.segments:
        if seg.aperture_state == ApertureState.Off:
            if len(current) >= 3:
                contours.append(current)
            current = [(seg.stop_x, seg.stop_y)]
            continue
        if not current:
            current = [(seg.start_x, seg.start_y)]
        if seg.arc_segment is not None:
            # Skip the first sample -- it coincides with the current endpoint.
            current.extend(arc_points(seg.arc_segment)[1:])
        else:
            current.append((seg.stop_x, seg.stop_y))

    if len(current) >= 3:
        contours.append(current)

    if not contours:
        return _EMPTY, _NO_DIAGS

    geom: BaseGeometry = _EMPTY
    for contour in contours:
        # make_valid can emit line/point parts for degenerate (e.g.
        # collinear) contours; only polygonal area participates in the fill.
        ring = _polygonal_only(make_valid(Polygon(contour)))
        if ring.is_empty:
            continue
        # Even-odd combination: overlapping areas toggle.
        geom = geom.symmetric_difference(ring)
    return geom, _NO_DIAGS


def _polygonal_only(geom: BaseGeometry) -> BaseGeometry:
    """Strip non-areal parts (lines, points) from a geometry."""
    if isinstance(geom, Polygon) or geom.is_empty:
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    if not parts:
        return _EMPTY
    return unary_union(parts)
