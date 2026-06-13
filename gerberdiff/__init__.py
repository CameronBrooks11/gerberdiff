"""Diff tool for Gerber/Excellon PCB design files.

Two complementary engines share one parse layer: the raster engine
(``compute_diff`` / ``compute_full_diff``) renders revisions with Cairo and
XORs pixels for visual overlays; the geometry engine
(``compute_geometry_diff``) computes resolution-independent, attributed
changes on the vector geometry and is Cairo-free.
"""

__version__ = "0.29.1"

from typing import TYPE_CHECKING, Any

from gerberdiff.diff.diff_engine import SingleLayerDiff, compute_diff, compute_full_diff
from gerberdiff.diff.layer_matcher import LayerPair, match_layers
from gerberdiff.geometry import (
    GeometryChange,
    GeometryDiffResult,
    LayerGeometryDiff,
    compute_geometry_diff,
)
from gerberdiff.parse.excellon_parser import parse_excellon
from gerberdiff.parse.gerber_state import parse_gerber
from gerberdiff.render.viewport import Viewport, compute_viewport
from gerberdiff.types import (
    BoundingBox,
    Diagnostic,
    DiagnosticSeverity,
    DiffResult,
    GerberParseError,
    LayerDiffResult,
    LayerStatus,
    LayerType,
    ParsedImage,
    Region,
    RegionFill,
)

if TYPE_CHECKING:
    from gerberdiff.render.renderer import render_to_numpy, render_to_surface

# The rasteriser requires the native cairo library; import it lazily so that
# `import gerberdiff` -- and the Cairo-free parse/geometry pipelines -- work
# on systems without it (PEP 562 module __getattr__).
_LAZY_RENDER_ATTRS = ("render_to_numpy", "render_to_surface")


def __getattr__(name: str) -> Any:
    if name in _LAZY_RENDER_ATTRS:
        from gerberdiff.render import renderer

        return getattr(renderer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BoundingBox",
    # Diagnostics
    "Diagnostic",
    # Enums
    "DiagnosticSeverity",
    # Diff result types
    "DiffResult",
    # Geometry diff
    "GeometryChange",
    "GeometryDiffResult",
    # Exceptions
    "GerberParseError",
    "LayerDiffResult",
    "LayerGeometryDiff",
    "LayerPair",
    "LayerStatus",
    "LayerType",
    # Core IR types
    "ParsedImage",
    "Region",
    "RegionFill",
    "SingleLayerDiff",
    "Viewport",
    # Version
    "__version__",
    # Diff
    "compute_diff",
    "compute_full_diff",
    "compute_geometry_diff",
    "compute_viewport",
    # Layer matching
    "match_layers",
    "parse_excellon",
    # Parse
    "parse_gerber",
    # Render
    "render_to_numpy",
    "render_to_surface",
]
