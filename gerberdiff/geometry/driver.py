"""Directory-level geometry diff driver.

``compute_geometry_diff`` is the geometry-engine counterpart of
``diff_engine.compute_full_diff``: it pairs layer files with
``match_layers``, parses both revisions, expands geometry, runs the boolean
diff and attribution per layer, and assembles a
:class:`~gerberdiff.geometry.types.GeometryDiffResult`.

The geometry pipeline is Cairo-free.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from gerberdiff.geometry.attribute import OpChange, attribute_changes, partition_unchanged
from gerberdiff.geometry.geom_diff import boolean_layer_diff
from gerberdiff.geometry.layer_geometry import (
    LayerGeometry,
    build_layer_geometry,
    resolve_geometry,
)
from gerberdiff.geometry.types import (
    MM2_PER_IN2,
    GeometryChange,
    GeometryDiffResult,
    LayerGeometryDiff,
)
from gerberdiff.types import (
    Diagnostic,
    DiagnosticSeverity,
    GerberParseError,
    LayerStatus,
    LayerType,
    ParsedImage,
)

# Default tolerances (user-facing units; see docs/geometry-diff.md).
DEFAULT_MOVE_TOL_MM = 0.005  # 5 um: below this a matched pair is "unchanged"
DEFAULT_GATE_RADIUS_MM = 0.2  # max centroid distance to pair two ops
DEFAULT_AREA_TOL = 0.01  # 1% relative area delta still counts as same dims
DEFAULT_DUST_AREA_MM2 = 1e-6  # boolean-diff components below this are noise

_MM_PER_IN = 25.4


def compute_geometry_diff(
    before_dir: Path,
    after_dir: Path,
    *,
    layers: Sequence[str] | None = None,
    move_tol_mm: float = DEFAULT_MOVE_TOL_MM,
    gate_radius_mm: float = DEFAULT_GATE_RADIUS_MM,
    area_tol: float = DEFAULT_AREA_TOL,
    dust_area_mm2: float = DEFAULT_DUST_AREA_MM2,
    on_diagnostic: Callable[[Path, Diagnostic], None] | None = None,
) -> GeometryDiffResult:
    """Geometry-diff two directories of Gerber/Excellon layer files.

    Parameters
    ----------
    before_dir, after_dir:
        Directories containing the before and after layer files.
    layers:
        If given, only layers whose names appear in this sequence are diffed.
    move_tol_mm:
        Minimum centroid displacement (mm) for a matched pair to be reported
        as ``moved`` rather than unchanged.
    gate_radius_mm:
        Maximum centroid distance (mm) at which two ops can be considered
        the same object.
    area_tol:
        Relative area delta within which two matched ops still count as the
        same dimensions (distinguishes ``moved`` from ``resized``).
    dust_area_mm2:
        Boolean-difference components smaller than this (mm^2) are dropped
        as numeric noise.
    on_diagnostic:
        Called with ``(path, diagnostic)`` for every non-fatal parse or
        expansion diagnostic.

    Raises
    ------
    GerberParseError
        When a file contains a fatal (``Error``-severity) parse diagnostic.
    OSError
        When a layer file cannot be read.
    """
    from gerberdiff.diff.layer_matcher import EXCELLON_SUFFIXES, match_layers
    from gerberdiff.parse.excellon_parser import parse_excellon
    from gerberdiff.parse.gerber_state import parse_gerber

    move_tol_in = move_tol_mm / _MM_PER_IN
    gate_radius_in = gate_radius_mm / _MM_PER_IN
    dust_area_in2 = dust_area_mm2 / MM2_PER_IN2

    def _parse(path: Path) -> ParsedImage:
        content = path.read_text(errors="replace")
        if path.suffix.lower() in EXCELLON_SUFFIXES:
            img = parse_excellon(content, source_path=path)
        else:
            img = parse_gerber(content, source_path=path)
        for diag in img.diagnostics:
            if diag.severity == DiagnosticSeverity.Error:
                raise GerberParseError(path, diag.message, diag.line)
            if on_diagnostic is not None:
                on_diagnostic(path, diag)
        return img

    def _build(path: Path) -> LayerGeometry:
        geometry = build_layer_geometry(_parse(path))
        if on_diagnostic is not None:
            for diag in geometry.diagnostics:
                on_diagnostic(path, diag)
        return geometry

    pairs = match_layers(before_dir, after_dir)
    if layers is not None:
        pairs = [p for p in pairs if p.name in layers]

    result = GeometryDiffResult()
    for pair in pairs:
        if pair.status in (LayerStatus.Added, LayerStatus.Removed):
            src_path = pair.after_path if pair.status == LayerStatus.Added else pair.before_path
            assert src_path is not None  # invariant guaranteed by match_layers
            geometry = _build(src_path)
            total_mm2 = resolve_geometry(geometry.ops).area * MM2_PER_IN2
            result.layers.append(
                LayerGeometryDiff(
                    name=pair.name,
                    layer_type=pair.layer_type,
                    status=pair.status,
                    added_area_mm2=total_mm2 if pair.status == LayerStatus.Added else 0.0,
                    removed_area_mm2=total_mm2 if pair.status == LayerStatus.Removed else 0.0,
                )
            )
            continue

        assert pair.before_path is not None and pair.after_path is not None
        geom_a = _build(pair.before_path)
        geom_b = _build(pair.after_path)
        result.layers.append(
            _diff_layer_pair(
                pair.name,
                pair.layer_type,
                geom_a,
                geom_b,
                move_tol_in=move_tol_in,
                gate_radius_in=gate_radius_in,
                area_tol=area_tol,
                dust_area_in2=dust_area_in2,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _diff_layer_pair(
    name: str,
    layer_type: LayerType,
    geom_a: LayerGeometry,
    geom_b: LayerGeometry,
    *,
    move_tol_in: float,
    gate_radius_in: float,
    area_tol: float,
    dust_area_in2: float,
) -> LayerGeometryDiff:
    parts = partition_unchanged(geom_a.ops, geom_b.ops)

    added_geom, removed_geom = boolean_layer_diff(
        geom_a,
        geom_b,
        parts.a_only,
        parts.b_only,
        parts.unchanged_a,
        dust_area=dust_area_in2,
    )

    op_changes, unchanged_count = attribute_changes(
        parts,
        move_tol=move_tol_in,
        gate_radius=gate_radius_in,
        area_tol=area_tol,
    )

    changes = [_to_public_change(c) for c in op_changes]
    # Top-of-board first (descending Y), then left-to-right -- matches the
    # raster engine's region ordering.
    changes.sort(key=lambda c: (-c.centroid_y, c.centroid_x))

    return LayerGeometryDiff(
        name=name,
        layer_type=layer_type,
        status=LayerStatus.Matched,
        changes=changes,
        unchanged_count=unchanged_count,
        added_area_mm2=added_geom.area * MM2_PER_IN2,
        removed_area_mm2=removed_geom.area * MM2_PER_IN2,
    )


def _to_public_change(change: OpChange) -> GeometryChange:
    """Convert an engine-internal OpChange to the public GeometryChange."""
    primary = change.after if change.after is not None else change.before
    assert primary is not None  # every OpChange has at least one side
    moved_or_resized = change.before is not None and change.after is not None
    return GeometryChange(
        kind=change.kind,
        op_kind=primary.kind,
        centroid_x=primary.centroid_x,
        centroid_y=primary.centroid_y,
        area_mm2=primary.area * MM2_PER_IN2,
        dx_mm=change.dx * _MM_PER_IN if moved_or_resized else None,
        dy_mm=change.dy * _MM_PER_IN if moved_or_resized else None,
        net_name=primary.net_name,
        before_op=change.before.source if change.before is not None else None,
        after_op=change.after.source if change.after is not None else None,
        before_geom=change.before.geom if change.before is not None else None,
        after_geom=change.after.geom if change.after is not None else None,
    )
