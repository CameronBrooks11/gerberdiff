"""Assemble a ParsedImage into ordered, world-space expanded operations.

This is the geometry engine's equivalent of the renderer's compile+render
pass.  Each draw operation becomes an :class:`ExpandedOp` carrying:

- a **lazy** world-space geometry (layer transforms and step-and-repeat
  applied on first access),
- effective polarity (dark adds material, clear subtracts),
- a **source-based content signature** for exact-cancellation matching
  between revisions, computed without expanding any geometry,
- a conservative analytic bounding box (also computed without expansion),
- provenance (source op, aperture identity, net name) for attribution.

Laziness is the engine's core performance property: ops whose signatures
match between revisions (typically the vast majority) never pay for shapely
geometry construction at all.  Only changed ops -- and unchanged ops whose
bounding boxes interact with changed material -- are ever expanded.

Transform semantics mirror the renderer's CTM derivation exactly
(``renderer.py::_render_layer``): coordinates are transformed
``SR-translate -> scale -> rotation -> mirror``.

Block apertures **flatten into the outer replay sequence** with the flash
translation composed in.  A clear layer inside a block erases previously
drawn content globally (verified renderer behaviour), so effective polarity
is Clear when *any* enclosing context or the op's own layer is Clear.

Macro flashes are expanded eagerly: their evaluation can fail, and the
resulting Warning diagnostic must surface deterministically rather than
depending on which ops happen to be expanded.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from gerberdiff.geometry.expand import flash_geometry, region_geometry, stroke_geometry
from gerberdiff.parse.arc_math import arc_bounding_box
from gerberdiff.types import (
    Aperture,
    ApertureState,
    BlockAperture,
    CircleAperture,
    Diagnostic,
    DiagnosticSeverity,
    DrawOp,
    LayerState,
    MacroAperture,
    MirrorState,
    ObroundAperture,
    ParsedImage,
    Polarity,
    PolygonAperture,
    RectangleAperture,
    RegionFill,
)

# Maximum block-aperture nesting depth (matches renderer and parser limits).
_MAX_BLOCK_DEPTH = 10

# Affine transform: world = M @ p + t, stored as (a, b, d, e) and (tx, ty)
# in shapely's affine_transform convention (x' = a*x + b*y + tx, ...).
_Matrix = tuple[float, float, float, float]
_Offset = tuple[float, float]
_Bounds = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
_IDENTITY_M: _Matrix = (1.0, 0.0, 0.0, 1.0)
_ZERO_T: _Offset = (0.0, 0.0)

_EMPTY: BaseGeometry = Polygon()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ExpandedOp:
    """One draw operation with lazy world-space geometry and provenance."""

    polarity: Polarity
    kind: str  # "flash" | "stroke" | "region"
    signature: str  # content hash: cancels exactly across revisions
    ap_signature: str  # aperture identity (dims), for moved/resized logic
    dims_signature: str  # like ap_signature but orientation-normalised
    bounds: _Bounds  # conservative world-space bbox (no expansion needed)
    net_name: str | None
    source: DrawOp | RegionFill
    # Lazy expansion machinery (shared thunk across SR tiles).
    _expand: Callable[[], BaseGeometry] = field(repr=False)
    _m: _Matrix = field(repr=False)
    _t: _Offset = field(repr=False)
    _geom: BaseGeometry | None = field(default=None, repr=False)
    _centroid: tuple[float, float] | None = field(default=None, repr=False)

    @property
    def geom(self) -> BaseGeometry:
        """World-space geometry (expanded and transformed on first access)."""
        if self._geom is None:
            self._geom = _apply_affine(self._expand(), self._m, self._t)
        return self._geom

    @property
    def centroid_x(self) -> float:
        return self._centroid_xy()[0]

    @property
    def centroid_y(self) -> float:
        return self._centroid_xy()[1]

    @property
    def area(self) -> float:
        """Geometry area in square inches."""
        return self.geom.area

    def _centroid_xy(self) -> tuple[float, float]:
        if self._centroid is None:
            c = self.geom.centroid
            if c.is_empty:  # degenerate geometry: fall back to bbox centre
                self._centroid = (
                    (self.bounds[0] + self.bounds[2]) / 2.0,
                    (self.bounds[1] + self.bounds[3]) / 2.0,
                )
            else:
                self._centroid = (c.x, c.y)
        return self._centroid


@dataclass
class LayerGeometry:
    """All expanded operations of one parsed file, in replay order."""

    ops: list[ExpandedOp] = field(default_factory=list)
    has_clear: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_layer_geometry(parsed: ParsedImage) -> LayerGeometry:
    """Build the lazy expanded-op list for every draw operation of *parsed*."""
    result = LayerGeometry()
    _walk(
        draw_ops=parsed.draw_ops,
        apertures=parsed.apertures,
        layers=parsed.layers,
        outer_m=_IDENTITY_M,
        outer_t=_ZERO_T,
        outer_clear=False,
        depth=0,
        result=result,
    )
    result.has_clear = any(op.polarity == Polarity.Clear for op in result.ops)
    return result


def resolve_geometry(ops: list[ExpandedOp]) -> BaseGeometry:
    """Ordered polarity replay: dark runs union, clear runs subtract.

    Consecutive same-polarity ops are unioned in one call (associative), so
    the replay cost scales with the number of polarity *transitions*, not ops.
    Forces expansion of every op.
    """
    acc: BaseGeometry = _EMPTY
    i = 0
    n = len(ops)
    while i < n:
        j = i
        polarity = ops[i].polarity
        while j < n and ops[j].polarity == polarity:
            j += 1
        run = unary_union([op.geom for op in ops[i:j]])
        if polarity == Polarity.Dark:
            acc = run if acc.is_empty else acc.union(run)
        elif not acc.is_empty:
            acc = acc.difference(run)
        i = j
    return acc


# ---------------------------------------------------------------------------
# Replay walk (recursive over block apertures)
# ---------------------------------------------------------------------------


def _walk(
    draw_ops: list[DrawOp | RegionFill],
    apertures: dict[int, Aperture],
    layers: list[LayerState],
    outer_m: _Matrix,
    outer_t: _Offset,
    outer_clear: bool,
    depth: int,
    result: LayerGeometry,
) -> None:
    if depth >= _MAX_BLOCK_DEPTH:
        return  # matches renderer: silently skip over-deep nesting

    # Per-layer transform/tile cache.
    layer_cache: dict[int, tuple[_Matrix, list[_Offset], bool]] = {}

    def _layer_info(index: int) -> tuple[_Matrix, list[_Offset], bool] | None:
        if index < 0 or index >= len(layers):
            return None
        cached = layer_cache.get(index)
        if cached is not None:
            return cached
        ls = layers[index]
        info = (_layer_matrix(ls), _sr_tiles(ls), ls.polarity == Polarity.Clear)
        layer_cache[index] = info
        return info

    for item in draw_ops:
        info = _layer_info(item.layer_index)
        if info is None:
            continue
        layer_m, tiles, layer_clear = info
        polarity = Polarity.Clear if (outer_clear or layer_clear) else Polarity.Dark

        if isinstance(item, RegionFill):
            _emit_region(result, item, outer_m, outer_t, layer_m, tiles, polarity)
            continue

        op = item
        if op.aperture_state == ApertureState.Off:
            continue

        ap = apertures.get(op.aperture_index)

        if op.aperture_state == ApertureState.Flash and isinstance(ap, BlockAperture):
            # Flatten block content into this replay, per tile.
            for tile in tiles:
                m, t = _compose(outer_m, outer_t, layer_m, _mat_vec(layer_m, tile))
                # Block flash position translates in the (transformed) op space.
                bt = _vec_add(_mat_vec(m, (op.stop_x, op.stop_y)), t)
                _walk(
                    draw_ops=ap.draw_ops,
                    apertures=ap.apertures,
                    layers=ap.layers,
                    outer_m=m,
                    outer_t=bt,
                    outer_clear=polarity == Polarity.Clear,
                    depth=depth + 1,
                    result=result,
                )
            continue

        if op.aperture_state == ApertureState.Flash:
            _emit_flash(result, op, ap, outer_m, outer_t, layer_m, tiles, polarity)
        else:  # ApertureState.On
            _emit_stroke(result, op, ap, outer_m, outer_t, layer_m, tiles, polarity)


# ---------------------------------------------------------------------------
# Per-kind emit helpers (descriptor construction, no geometry expansion)
# ---------------------------------------------------------------------------


def _emit_flash(
    result: LayerGeometry,
    op: DrawOp,
    ap: Aperture | None,
    outer_m: _Matrix,
    outer_t: _Offset,
    layer_m: _Matrix,
    tiles: list[_Offset],
    polarity: Polarity,
) -> None:
    if ap is None:
        return

    if isinstance(ap, MacroAperture):
        # Eager: evaluation can fail and must warn deterministically.
        geom, diags = flash_geometry(op, ap)
        result.diagnostics.extend(diags)
        if geom.is_empty:
            return
        thunk = _const_thunk(geom)
        op_bounds: _Bounds = geom.bounds
    else:
        extents = _aperture_half_extents(ap)
        if extents is None:
            return
        hx, hy = extents
        x, y = op.stop_x, op.stop_y
        thunk = _memo_thunk(lambda: flash_geometry(op, ap)[0])
        op_bounds = (x - hx, y - hy, x + hx, y + hy)

    ap_sig, dims_sig = _aperture_signature(ap)
    base_sig = f"flash|{polarity.value}|{ap_sig}|{op.stop_x!r},{op.stop_y!r}"
    _emit_tiles(
        result,
        op,
        "flash",
        ap_sig,
        dims_sig,
        base_sig,
        op_bounds,
        thunk,
        op.attributes.get("N") if op.attributes else None,
        outer_m,
        outer_t,
        layer_m,
        tiles,
        polarity,
    )


def _emit_stroke(
    result: LayerGeometry,
    op: DrawOp,
    ap: Aperture | None,
    outer_m: _Matrix,
    outer_t: _Offset,
    layer_m: _Matrix,
    tiles: list[_Offset],
    polarity: Polarity,
) -> None:
    if ap is None or isinstance(ap, (BlockAperture, MacroAperture)):
        # Strokes with macro/block apertures are not meaningful; the raster
        # engine draws them with a hairline -- skip in the geometry engine.
        return
    extents = _aperture_half_extents(ap)
    if extents is None:
        return
    hx, hy = extents
    brush = max(hx, hy)  # conservative half-extent in any direction

    arc = op.arc_segment
    if arc is not None:
        bb = arc_bounding_box(arc, brush)
        op_bounds: _Bounds = (bb.min_x, bb.min_y, bb.max_x, bb.max_y)
        arc_sig = (
            f"|arc:{arc.center_x!r},{arc.center_y!r},{arc.radius!r},"
            f"{arc.start_angle_deg!r},{arc.end_angle_deg!r}"
        )
        if not isinstance(ap, CircleAperture):
            # Static decision: non-round arc strokes use the round-brush
            # approximation (see expand._arc_stroke).
            result.diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.Info,
                    message=(
                        f"arc stroke with {type(ap).__name__} approximated by "
                        f"a round brush of diameter {2.0 * brush:.6f} in"
                    ),
                )
            )
    else:
        op_bounds = (
            min(op.start_x, op.stop_x) - brush,
            min(op.start_y, op.stop_y) - brush,
            max(op.start_x, op.stop_x) + brush,
            max(op.start_y, op.stop_y) + brush,
        )
        arc_sig = ""

    ap_sig, dims_sig = _aperture_signature(ap)
    base_sig = (
        f"stroke|{polarity.value}|{ap_sig}"
        f"|{op.start_x!r},{op.start_y!r},{op.stop_x!r},{op.stop_y!r}{arc_sig}"
    )
    _emit_tiles(
        result,
        op,
        "stroke",
        ap_sig,
        dims_sig,
        base_sig,
        op_bounds,
        _memo_thunk(lambda: stroke_geometry(op, ap)[0]),
        op.attributes.get("N") if op.attributes else None,
        outer_m,
        outer_t,
        layer_m,
        tiles,
        polarity,
    )


def _emit_region(
    result: LayerGeometry,
    region: RegionFill,
    outer_m: _Matrix,
    outer_t: _Offset,
    layer_m: _Matrix,
    tiles: list[_Offset],
    polarity: Polarity,
) -> None:
    bounds = _region_bounds(region)
    if bounds is None:
        return  # degenerate region (no drawable contour)
    sig_parts = [f"region|{polarity.value}"]
    for seg in region.segments:
        arc = seg.arc_segment
        arc_sig = (
            f";{arc.center_x!r},{arc.center_y!r},{arc.radius!r},"
            f"{arc.start_angle_deg!r},{arc.end_angle_deg!r}"
            if arc is not None
            else ""
        )
        sig_parts.append(
            f"{seg.aperture_state.value}:{seg.start_x!r},{seg.start_y!r},"
            f"{seg.stop_x!r},{seg.stop_y!r}{arc_sig}"
        )
    _emit_tiles(
        result,
        region,
        "region",
        "region",
        "region",
        "|".join(sig_parts),
        bounds,
        _memo_thunk(lambda: region_geometry(region)[0]),
        None,
        outer_m,
        outer_t,
        layer_m,
        tiles,
        polarity,
    )


def _emit_tiles(
    result: LayerGeometry,
    source: DrawOp | RegionFill,
    kind: str,
    ap_signature: str,
    dims_signature: str,
    base_signature: str,
    op_bounds: _Bounds,
    thunk: Callable[[], BaseGeometry],
    net_name: str | None,
    outer_m: _Matrix,
    outer_t: _Offset,
    layer_m: _Matrix,
    tiles: list[_Offset],
    polarity: Polarity,
) -> None:
    for tile in tiles:
        m, t = _compose(outer_m, outer_t, layer_m, _mat_vec(layer_m, tile))
        signature = _hash_signature(f"{base_signature}|affine:{m!r},{t!r}")
        result.ops.append(
            ExpandedOp(
                polarity=polarity,
                kind=kind,
                signature=signature,
                ap_signature=ap_signature,
                dims_signature=dims_signature,
                bounds=_transform_bounds(op_bounds, m, t),
                net_name=net_name,
                source=source,
                _expand=thunk,
                _m=m,
                _t=t,
            )
        )


# ---------------------------------------------------------------------------
# Lazy-expansion helpers
# ---------------------------------------------------------------------------


def _memo_thunk(fn: Callable[[], BaseGeometry]) -> Callable[[], BaseGeometry]:
    """Memoise an expansion function so SR tiles share one op-space geometry."""
    cache: list[BaseGeometry] = []

    def thunk() -> BaseGeometry:
        if not cache:
            cache.append(fn())
        return cache[0]

    return thunk


def _const_thunk(geom: BaseGeometry) -> Callable[[], BaseGeometry]:
    return lambda: geom


def _aperture_half_extents(ap: Aperture) -> tuple[float, float] | None:
    """Analytic half-extents of a simple aperture, or None if degenerate.

    Mirrors the validity checks in ``expand._aperture_outline``.
    """
    match ap:
        case CircleAperture():
            if ap.diameter <= 0.0:
                return None
            r = ap.diameter / 2.0
            return (r, r)
        case RectangleAperture() | ObroundAperture():
            if ap.width <= 0.0 or ap.height <= 0.0:
                return None
            return (ap.width / 2.0, ap.height / 2.0)
        case PolygonAperture():
            if ap.outer_diameter <= 0.0 or ap.num_vertices < 3:
                return None
            r = ap.outer_diameter / 2.0
            return (r, r)
    return None


def _region_bounds(region: RegionFill) -> _Bounds | None:
    """Conservative bbox of a region fill, or None when degenerate."""
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    on_segments = 0
    for seg in region.segments:
        if seg.aperture_state != ApertureState.Off:
            on_segments += 1
        arc = seg.arc_segment
        if arc is not None:
            bb = arc_bounding_box(arc)
            min_x = min(min_x, bb.min_x)
            min_y = min(min_y, bb.min_y)
            max_x = max(max_x, bb.max_x)
            max_y = max(max_y, bb.max_y)
        else:
            min_x = min(min_x, seg.start_x, seg.stop_x)
            min_y = min(min_y, seg.start_y, seg.stop_y)
            max_x = max(max_x, seg.start_x, seg.stop_x)
            max_y = max(max_y, seg.start_y, seg.stop_y)
    if on_segments < 2 or not math.isfinite(min_x):
        return None
    return (min_x, min_y, max_x, max_y)


def _transform_bounds(b: _Bounds, m: _Matrix, t: _Offset) -> _Bounds:
    """Map a bbox through an affine; the corner hull stays conservative."""
    if m == _IDENTITY_M and t == _ZERO_T:
        return b
    corners = (
        _vec_add(_mat_vec(m, (b[0], b[1])), t),
        _vec_add(_mat_vec(m, (b[2], b[1])), t),
        _vec_add(_mat_vec(m, (b[2], b[3])), t),
        _vec_add(_mat_vec(m, (b[0], b[3])), t),
    )
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def _hash_signature(content: str) -> str:
    """Hash a source-content signature string.

    Identical source text parses to identical floats, whose ``repr`` is
    exact, so an unchanged op yields a bit-identical signature across
    revisions -- without constructing any geometry.  Aperture identity is by
    *content*, so D-code renumbering between files does not break matching.
    """
    return hashlib.sha1(content.encode()).hexdigest()


def _aperture_signature(ap: Aperture | None) -> tuple[str, str]:
    """Stable identity of an aperture's shape parameters (not its D-code).

    Returns ``(exact, orientation_normalised)``.  The normalised form treats
    a 90-degree-rotated rect/obround (W and H swapped) and a re-phased
    regular polygon as the *same dimensions*, so a rotated footprint
    classifies as ``moved`` rather than ``resized``.
    """
    match ap:
        case CircleAperture():
            sig = f"circle:{ap.diameter!r}:{ap.hole_diameter!r}"
            return sig, sig
        case RectangleAperture():
            lo, hi = sorted((ap.width, ap.height))
            return (
                f"rect:{ap.width!r}x{ap.height!r}:{ap.hole_diameter!r}",
                f"rect:{lo!r}x{hi!r}:{ap.hole_diameter!r}",
            )
        case ObroundAperture():
            lo, hi = sorted((ap.width, ap.height))
            return (
                f"obround:{ap.width!r}x{ap.height!r}:{ap.hole_diameter!r}",
                f"obround:{lo!r}x{hi!r}:{ap.hole_diameter!r}",
            )
        case PolygonAperture():
            return (
                f"polygon:{ap.outer_diameter!r}:{ap.num_vertices}"
                f":{ap.rotation!r}:{ap.hole_diameter!r}",
                f"polygon:{ap.outer_diameter!r}:{ap.num_vertices}:{ap.hole_diameter!r}",
            )
        case MacroAperture():
            name = ap.macro_def.name if ap.macro_def is not None else "?"
            params = ",".join(repr(p) for p in ap.params)
            sig = f"macro:{name}:{params}:{ap.unit_scale!r}"
            return sig, sig
        case _:
            return "none", "none"


# ---------------------------------------------------------------------------
# Affine helpers
# ---------------------------------------------------------------------------


def _layer_matrix(ls: LayerState) -> _Matrix:
    """Layer transform M = Mirror @ Rotation @ Scale (renderer CTM order)."""
    s = ls.scale
    theta = math.radians(ls.rotation)
    c, sn = math.cos(theta), math.sin(theta)
    sx = -1.0 if ls.mirror in (MirrorState.FlipA, MirrorState.FlipAB) else 1.0
    sy = -1.0 if ls.mirror in (MirrorState.FlipB, MirrorState.FlipAB) else 1.0
    # Mir @ Rot @ Scale, row-major (a, b, d, e).
    return (sx * c * s, -sx * sn * s, sy * sn * s, sy * c * s)


def _sr_tiles(ls: LayerState) -> list[_Offset]:
    """Step-and-repeat tile offsets (in pre-transform op space)."""
    sr = ls.step_and_repeat
    if sr.x <= 1 and sr.y <= 1:
        return [_ZERO_T]
    return [
        (ix * sr.dist_x, iy * sr.dist_y) for ix in range(max(1, sr.x)) for iy in range(max(1, sr.y))
    ]


def _compose(m1: _Matrix, t1: _Offset, m2: _Matrix, t2: _Offset) -> tuple[_Matrix, _Offset]:
    """Compose two affines: apply (m2, t2) first, then (m1, t1)."""
    a1, b1, d1, e1 = m1
    a2, b2, d2, e2 = m2
    m = (
        a1 * a2 + b1 * d2,
        a1 * b2 + b1 * e2,
        d1 * a2 + e1 * d2,
        d1 * b2 + e1 * e2,
    )
    t = _vec_add(_mat_vec(m1, t2), t1)
    return m, t


def _mat_vec(m: _Matrix, v: _Offset) -> _Offset:
    a, b, d, e = m
    return (a * v[0] + b * v[1], d * v[0] + e * v[1])


def _vec_add(u: _Offset, v: _Offset) -> _Offset:
    return (u[0] + v[0], u[1] + v[1])


def _apply_affine(geom: BaseGeometry, m: _Matrix, t: _Offset) -> BaseGeometry:
    if m == _IDENTITY_M and t == _ZERO_T:
        return geom
    a, b, d, e = m
    return affinity.affine_transform(geom, [a, b, d, e, t[0], t[1]])
