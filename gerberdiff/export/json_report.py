"""Export diff results as a versioned JSON report.

Schema (version 1)
------------------
See ``docs/schema.md`` for canonical documentation.

All coordinate values are in **inches**.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gerberdiff.types import DiffResult, LayerDiffResult, LayerStatus, Region

_SCHEMA_VERSION = 1
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
# Internal helpers
# ---------------------------------------------------------------------------


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
