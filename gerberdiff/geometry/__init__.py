"""Geometry-aware diff engine: resolution-independent, attributed changes.

Public surface:

- :func:`compute_geometry_diff` -- directory-vs-directory geometry diff.
- :class:`GeometryChange`, :class:`LayerGeometryDiff`,
  :class:`GeometryDiffResult` -- result types.

The geometry pipeline operates on the parsed IR and is Cairo-free; see
``docs/geometry-diff.md`` for the design.
"""

from gerberdiff.geometry.driver import (
    DEFAULT_AREA_TOL,
    DEFAULT_DUST_AREA_MM2,
    DEFAULT_GATE_RADIUS_MM,
    DEFAULT_MOVE_TOL_MM,
    compute_geometry_diff,
)
from gerberdiff.geometry.types import (
    ChangeKind,
    GeometryChange,
    GeometryDiffResult,
    LayerGeometryDiff,
)

__all__ = [
    "DEFAULT_AREA_TOL",
    "DEFAULT_DUST_AREA_MM2",
    "DEFAULT_GATE_RADIUS_MM",
    "DEFAULT_MOVE_TOL_MM",
    "ChangeKind",
    "GeometryChange",
    "GeometryDiffResult",
    "LayerGeometryDiff",
    "compute_geometry_diff",
]
