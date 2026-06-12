"""Assemble a ParsedImage into ordered, world-space expanded operations.

This is the geometry engine's equivalent of the renderer's compile+render
pass.  Each draw operation expands to an :class:`ExpandedOp` carrying:

- world-space geometry (layer transforms and step-and-repeat applied),
- effective polarity (dark adds material, clear subtracts),
- a content signature for exact-cancellation matching between revisions,
- provenance (source op, aperture identity, net name) for attribution.

Transform semantics mirror the renderer's CTM derivation exactly
(``renderer.py::_render_layer``): coordinates are transformed
``SR-translate -> scale -> rotation -> mirror``.

Block apertures **flatten into the outer replay sequence** with the flash
translation composed in.  A clear layer inside a block erases previously
drawn content globally (verified renderer behaviour), so effective polarity
is Clear when *any* enclosing context or the op's own layer is Clear.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from gerberdiff.geometry.expand import flash_geometry, region_geometry, stroke_geometry
from gerberdiff.types import (
    Aperture,
    ApertureState,
    BlockAperture,
    CircleAperture,
    Diagnostic,
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
_IDENTITY_M: _Matrix = (1.0, 0.0, 0.0, 1.0)
_ZERO_T: _Offset = (0.0, 0.0)

_EMPTY: BaseGeometry = Polygon()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ExpandedOp:
    """One draw operation expanded to world-space geometry with provenance."""

    geom: BaseGeometry
    polarity: Polarity
    kind: str  # "flash" | "stroke" | "region"
    signature: str  # content hash: cancels exactly across revisions
    ap_signature: str  # aperture identity (dims), for moved/resized logic
    dims_signature: str  # like ap_signature but orientation-normalised
    centroid_x: float
    centroid_y: float
    area: float  # square inches
    net_name: str | None
    source: DrawOp | RegionFill


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
    """Expand every draw operation of *parsed* into world-space geometry."""
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
        m = _layer_matrix(ls)
        tiles = _sr_tiles(ls)
        info = (m, tiles, ls.polarity == Polarity.Clear)
        layer_cache[index] = info
        return info

    for item in draw_ops:
        info = _layer_info(item.layer_index)
        if info is None:
            continue
        layer_m, tiles, layer_clear = info
        polarity = Polarity.Clear if (outer_clear or layer_clear) else Polarity.Dark

        if isinstance(item, RegionFill):
            geom, diags = region_geometry(item)
            result.diagnostics.extend(diags)
            _emit_tiles(
                result,
                geom,
                item,
                "region",
                ("region", "region"),
                None,
                outer_m,
                outer_t,
                layer_m,
                tiles,
                polarity,
            )
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
            geom, diags = flash_geometry(op, ap)
            kind = "flash"
        else:  # ApertureState.On
            geom, diags = stroke_geometry(op, ap)
            kind = "stroke"
        result.diagnostics.extend(diags)
        net_name = op.attributes.get("N") if op.attributes else None
        _emit_tiles(
            result,
            geom,
            op,
            kind,
            _aperture_signature(ap),
            net_name,
            outer_m,
            outer_t,
            layer_m,
            tiles,
            polarity,
        )


def _emit_tiles(
    result: LayerGeometry,
    geom: BaseGeometry,
    source: DrawOp | RegionFill,
    kind: str,
    signatures: tuple[str, str],
    net_name: str | None,
    outer_m: _Matrix,
    outer_t: _Offset,
    layer_m: _Matrix,
    tiles: list[_Offset],
    polarity: Polarity,
) -> None:
    if geom.is_empty:
        return
    ap_signature, dims_signature = signatures
    for tile in tiles:
        m, t = _compose(outer_m, outer_t, layer_m, _mat_vec(layer_m, tile))
        world = _apply_affine(geom, m, t)
        if world.is_empty:
            continue
        centroid = world.centroid
        result.ops.append(
            ExpandedOp(
                geom=world,
                polarity=polarity,
                kind=kind,
                signature=_content_signature(world, polarity, kind),
                ap_signature=ap_signature,
                dims_signature=dims_signature,
                centroid_x=centroid.x,
                centroid_y=centroid.y,
                area=world.area,
                net_name=net_name,
                source=source,
            )
        )


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------


def _content_signature(geom: BaseGeometry, polarity: Polarity, kind: str) -> str:
    """Identity hash of the final world-space geometry.

    Identical source text parses to identical floats and expands through the
    same deterministic construction, so an unchanged op yields a bit-identical
    WKB across revisions.  Matching on the *result* geometry also cancels ops
    that are equal despite different D-code numbering between files.
    """
    h = hashlib.sha1(geom.wkb)
    h.update(polarity.value.encode())
    h.update(kind.encode())
    return h.hexdigest()


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
