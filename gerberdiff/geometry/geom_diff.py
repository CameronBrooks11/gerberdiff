"""Per-layer boolean difference between two revisions' geometry.

Produces (added, removed) material as polygonal geometry:

    added   = geometry(B) \\ geometry(A)
    removed = geometry(A) \\ geometry(B)

Fast path (all-dark layers, the overwhelmingly common case)
-----------------------------------------------------------
Ops whose content signature appears in both revisions cancel *exactly*, so
only changed ops plus the unchanged ops that spatially interact with them
need to enter the boolean math:

    added   = union(B_only) \\ (union(A_only) | union(context))
    removed = union(A_only) \\ (union(B_only) | union(context))

where ``context`` is the unchanged material whose bounding boxes intersect
any changed op (STRtree query).  This is exact -- unchanged material that
touches no changed material cannot affect either difference -- and shrinks
the union cost from thousands of ops to the changed neighbourhood.

Full path
---------
Any clear-polarity content (either side) invalidates the flat-union model;
fall back to the ordered polarity replay (``resolve_geometry``) on both
sides and difference the resolved geometry.  Correct, slower.
"""

from __future__ import annotations

from shapely import set_precision
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from gerberdiff.geometry.layer_geometry import ExpandedOp, LayerGeometry, resolve_geometry

# Snap-rounding grid for boolean robustness (inches).  Far below any
# manufacturable feature; kills float-noise slivers without moving geometry.
_GRID_IN = 1e-8

_EMPTY: BaseGeometry = Polygon()


def boolean_layer_diff(
    a: LayerGeometry,
    b: LayerGeometry,
    a_only: list[ExpandedOp],
    b_only: list[ExpandedOp],
    unchanged: list[ExpandedOp],
    *,
    dust_area: float = 0.0,
) -> tuple[BaseGeometry, BaseGeometry]:
    """Return ``(added, removed)`` polygonal geometry in square-inch space.

    *a_only*, *b_only*, *unchanged* come from
    :func:`gerberdiff.geometry.attribute.partition_unchanged`.  *unchanged*
    may be either side's list (the geometry is identical by construction).
    *dust_area* drops difference components smaller than this area (in^2).
    """
    if a.has_clear or b.has_clear:
        geom_a = resolve_geometry(a.ops)
        geom_b = resolve_geometry(b.ops)
        added = _safe_difference(geom_b, geom_a)
        removed = _safe_difference(geom_a, geom_b)
        return _drop_dust(added, dust_area), _drop_dust(removed, dust_area)

    if not a_only and not b_only:
        return _EMPTY, _EMPTY

    u_a_only = unary_union([op.geom for op in a_only]) if a_only else _EMPTY
    u_b_only = unary_union([op.geom for op in b_only]) if b_only else _EMPTY
    context = _interacting_context(unchanged, a_only, b_only)

    added = _safe_difference(u_b_only, u_a_only.union(context))
    removed = _safe_difference(u_a_only, u_b_only.union(context))
    return _drop_dust(added, dust_area), _drop_dust(removed, dust_area)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _interacting_context(
    unchanged: list[ExpandedOp],
    a_only: list[ExpandedOp],
    b_only: list[ExpandedOp],
) -> BaseGeometry:
    """Union of unchanged ops whose bboxes intersect any changed op."""
    if not unchanged:
        return _EMPTY
    tree = STRtree([op.geom for op in unchanged])
    hit_indices: set[int] = set()
    for op in a_only:
        hit_indices.update(int(i) for i in tree.query(op.geom))
    for op in b_only:
        hit_indices.update(int(i) for i in tree.query(op.geom))
    if not hit_indices:
        return _EMPTY
    return unary_union([unchanged[i].geom for i in sorted(hit_indices)])


def _safe_difference(minuend: BaseGeometry, subtrahend: BaseGeometry) -> BaseGeometry:
    """Snap-rounded difference, robust against float-noise topology errors."""
    if minuend.is_empty:
        return _EMPTY
    if subtrahend.is_empty:
        return minuend
    m = set_precision(minuend, _GRID_IN)
    s = set_precision(subtrahend, _GRID_IN)
    return m.difference(s)


def _drop_dust(geom: BaseGeometry, dust_area: float) -> BaseGeometry:
    """Keep only polygonal components with area >= *dust_area*."""
    polys = [p for p in _polygon_parts(geom) if not p.is_empty and p.area >= dust_area]
    if not polys:
        return _EMPTY
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)


def _polygon_parts(geom: BaseGeometry) -> list[Polygon]:
    """Flatten any geometry to its polygonal parts (drops lines/points)."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    parts: list[Polygon] = []
    if hasattr(geom, "geoms"):
        for g in geom.geoms:
            parts.extend(_polygon_parts(g))
    return parts
