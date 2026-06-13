"""Per-layer boolean difference between two revisions' geometry.

Produces (added, removed) material as polygonal geometry:

    added   = geometry(B) \\ geometry(A)
    removed = geometry(A) \\ geometry(B)

Fast path (all-dark layers, the overwhelmingly common case)
-----------------------------------------------------------
Ops whose content signature appears in both revisions cancel *exactly* and
are never expanded.  Only changed ops enter the boolean math:

    added_raw   = union(B_only) \\ union(A_only)
    removed_raw = union(A_only) \\ union(B_only)

Unchanged material can still mask part of a raw difference (e.g. a removed
trace running under an unchanged pad), so each raw result is then reduced
by the unchanged ops whose bounding boxes intersect it:

    added   = added_raw   \\ union(interacting unchanged)
    removed = removed_raw \\ union(interacting unchanged)

This is exact -- unchanged material that does not intersect a raw
difference cannot affect it -- and the bbox query uses the ops' analytic
bounds, so non-interacting unchanged ops are never expanded at all.

All differences are snap-rounded via GEOS ``grid_size`` for numeric
robustness (no separate ``set_precision`` pass).

Full path
---------
Any clear-polarity content (either side) invalidates the flat-union model;
fall back to the ordered polarity replay (``resolve_geometry``) on both
sides and difference the resolved geometry.  Correct, slower.
"""

from __future__ import annotations

import shapely
from shapely.geometry import MultiPolygon, Polygon, box
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
        added = _difference(geom_b, geom_a)
        removed = _difference(geom_a, geom_b)
        return _drop_dust(added, dust_area), _drop_dust(removed, dust_area)

    if not a_only and not b_only:
        return _EMPTY, _EMPTY

    u_a_only = unary_union([op.geom for op in a_only]) if a_only else _EMPTY
    u_b_only = unary_union([op.geom for op in b_only]) if b_only else _EMPTY

    added_raw = _difference(u_b_only, u_a_only)
    removed_raw = _difference(u_a_only, u_b_only)

    # Reduce by unchanged material that intersects the raw differences.
    # The raw results are small (the changed neighbourhood), so the masked
    # differences are cheap even on dense layers.
    tree = _bounds_tree(unchanged)
    added = _subtract_interacting(added_raw, unchanged, tree)
    removed = _subtract_interacting(removed_raw, unchanged, tree)
    return _drop_dust(added, dust_area), _drop_dust(removed, dust_area)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bounds_tree(ops: list[ExpandedOp]) -> STRtree | None:
    """STRtree over the ops' analytic bounding boxes (no expansion)."""
    if not ops:
        return None
    return STRtree([box(*op.bounds) for op in ops])


def _subtract_interacting(
    raw: BaseGeometry,
    unchanged: list[ExpandedOp],
    tree: STRtree | None,
) -> BaseGeometry:
    """Subtract unchanged ops whose bboxes intersect *raw* from it."""
    if raw.is_empty or tree is None:
        return raw
    hit_indices: set[int] = set()
    for part in _polygon_parts(raw):
        hit_indices.update(int(i) for i in tree.query(part))
    if not hit_indices:
        return raw
    context = unary_union([unchanged[i].geom for i in sorted(hit_indices)])
    return _difference(raw, context)


def _difference(minuend: BaseGeometry, subtrahend: BaseGeometry) -> BaseGeometry:
    """Snap-rounded difference, robust against float-noise topology errors."""
    if minuend.is_empty:
        return _EMPTY
    if subtrahend.is_empty:
        return minuend
    return shapely.difference(minuend, subtrahend, grid_size=_GRID_IN)


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
