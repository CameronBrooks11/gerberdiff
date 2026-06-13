"""Export diff results as a versioned JSON report.

Schemas
-------
- Version 1: raster pixel diff (``DiffResult``).
- Version 2: geometry diff (``GeometryDiffResult``), ``"mode": "geometry"``.

See ``docs/schema.md`` for canonical documentation.

Coordinate values are in **inches**; geometry areas are in **mm^2** and
displacements in **mm** (see ``gerberdiff/geometry/types.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gerberdiff.geometry.types import GeometryChange, GeometryDiffResult, LayerGeometryDiff
from gerberdiff.types import DiffResult, LayerDiffResult, LayerStatus, Region

_SCHEMA_VERSION = 1
_GEOMETRY_SCHEMA_VERSION = 2
_GENERATOR = "gerberdiff"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_report(diff_result: DiffResult) -> dict[str, Any]:
    """Serialize *diff_result* to a JSON-compatible dictionary.

    The returned dict can be passed directly to ``json.dumps`` / ``json.dump``.
    """
    changed_layers = sum(
        1
        for lr in diff_result.layers
        if lr.changed_pixel_count > 0 or lr.status != LayerStatus.Matched
    )
    total_regions = sum(len(lr.regions) for lr in diff_result.layers)

    return {
        "version": _SCHEMA_VERSION,
        "generator": _GENERATOR,
        "summary": {
            "changed_layers": changed_layers,
            "total_regions": total_regions,
            "has_changes": diff_result.has_changes,
        },
        "layers": [_serialize_layer(lr) for lr in diff_result.layers],
    }


def write_report(diff_result: DiffResult, output_path: Path, overwrite: bool = False) -> None:
    """Write the JSON report to *output_path*.

    Raises
    ------
    FileExistsError
        If *output_path* already exists and *overwrite* is ``False``.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output file already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(diff_result)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Geometry report (schema version 2)
# ---------------------------------------------------------------------------


def build_geometry_report(
    result: GeometryDiffResult,
    tolerances: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Serialize a geometry diff result to a JSON-compatible dictionary.

    *tolerances* (optional) records the classification thresholds used, for
    reproducibility (keys: ``move_tol_mm``, ``gate_radius_mm``, ``area_tol``,
    ``dust_area_mm2``).
    """
    report: dict[str, Any] = {
        "version": _GEOMETRY_SCHEMA_VERSION,
        "generator": _GENERATOR,
        "mode": "geometry",
        "summary": {
            "changed_layers": sum(1 for layer in result.layers if layer.has_changes),
            "total_changes": sum(len(layer.changes) for layer in result.layers),
            "has_changes": result.has_changes,
        },
        "layers": [_serialize_geometry_layer(layer) for layer in result.layers],
    }
    if tolerances is not None:
        report["tolerances"] = tolerances
    return report


def write_geometry_report(
    result: GeometryDiffResult,
    output_path: Path,
    tolerances: dict[str, float] | None = None,
    overwrite: bool = False,
) -> None:
    """Write the geometry JSON report to *output_path*.

    Raises
    ------
    FileExistsError
        If *output_path* already exists and *overwrite* is ``False``.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output file already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_geometry_report(result, tolerances)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_geometry_layer(layer: LayerGeometryDiff) -> dict[str, Any]:
    return {
        "name": layer.name,
        "status": layer.status,
        "layer_type": layer.layer_type,
        "unchanged_count": layer.unchanged_count,
        "added_area_mm2": round(layer.added_area_mm2, 6),
        "removed_area_mm2": round(layer.removed_area_mm2, 6),
        "counts": {
            "added": layer.count("added"),
            "removed": layer.count("removed"),
            "moved": layer.count("moved"),
            "resized": layer.count("resized"),
        },
        "changes": [_serialize_geometry_change(c) for c in layer.changes],
    }


def _serialize_geometry_change(c: GeometryChange) -> dict[str, Any]:
    return {
        "kind": c.kind,
        "op_kind": c.op_kind,
        "centroid_x": c.centroid_x,
        "centroid_y": c.centroid_y,
        "area_mm2": round(c.area_mm2, 6),
        "dx_mm": round(c.dx_mm, 6) if c.dx_mm is not None else None,
        "dy_mm": round(c.dy_mm, 6) if c.dy_mm is not None else None,
        "net": c.net_name,
    }


def _serialize_layer(lr: LayerDiffResult) -> dict[str, Any]:
    return {
        "name": lr.name,
        "status": lr.status,
        "layer_type": lr.layer_type,
        "changed_pixel_count": lr.changed_pixel_count,
        "total_pixel_count": lr.total_pixel_count,
        "changed_fraction": round(lr.changed_fraction, 8),
        "regions": [_serialize_region(r) for r in lr.regions],
    }


def _serialize_region(r: Region) -> dict[str, Any]:
    bb = r.bounding_box
    return {
        "id": r.id,
        "centroid_x": r.centroid_x,
        "centroid_y": r.centroid_y,
        "bbox": {
            "min_x": bb.min_x,
            "min_y": bb.min_y,
            "max_x": bb.max_x,
            "max_y": bb.max_y,
        },
        "pixel_count": r.pixel_count,
    }
