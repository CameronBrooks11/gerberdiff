"""Public result types for the geometry diff engine.

Unit conventions (documented in ``docs/schema.md``):

- ``centroid_x`` / ``centroid_y`` are in **inches** (matching the raster
  engine's ``Region`` convention),
- areas are in **mm^2**,
- ``dx_mm`` / ``dy_mm`` displacements are in **mm**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from gerberdiff.types import DrawOp, LayerStatus, LayerType, RegionFill

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

ChangeKind = Literal["added", "removed", "moved", "resized"]

# mm^2 per square inch.
MM2_PER_IN2 = 25.4 * 25.4


@dataclass
class GeometryChange:
    """One attributed change on a layer.

    ``centroid_*`` and ``area_mm2`` describe the after-state object when one
    exists (added/moved/resized) and the before-state object otherwise
    (removed).  ``before_geom`` / ``after_geom`` carry the shapely polygons
    for programmatic/SVG use; they are excluded from ``repr`` and JSON.
    """

    kind: ChangeKind
    op_kind: str  # flash | stroke | region
    centroid_x: float  # inches
    centroid_y: float  # inches
    area_mm2: float
    dx_mm: float | None = None  # moved/resized: after - before
    dy_mm: float | None = None
    net_name: str | None = None
    before_op: DrawOp | RegionFill | None = field(default=None, repr=False)
    after_op: DrawOp | RegionFill | None = field(default=None, repr=False)
    before_geom: BaseGeometry | None = field(default=None, repr=False)
    after_geom: BaseGeometry | None = field(default=None, repr=False)


@dataclass
class LayerGeometryDiff:
    """Geometry diff result for one matched/added/removed layer pair."""

    name: str
    layer_type: LayerType
    status: LayerStatus  # matched | added | removed
    changes: list[GeometryChange] = field(default_factory=list)
    unchanged_count: int = 0
    added_area_mm2: float = 0.0
    removed_area_mm2: float = 0.0

    def count(self, kind: ChangeKind) -> int:
        """Number of changes of the given *kind*."""
        return sum(1 for c in self.changes if c.kind == kind)

    @property
    def has_changes(self) -> bool:
        return (
            bool(self.changes)
            or self.status != LayerStatus.Matched
            or self.added_area_mm2 > 0.0
            or self.removed_area_mm2 > 0.0
        )


@dataclass
class GeometryDiffResult:
    """Full geometry diff across all matched layers."""

    layers: list[LayerGeometryDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(layer.has_changes for layer in self.layers)
