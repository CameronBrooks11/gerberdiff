__version__ = "0.29.0"

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
from gerberdiff.render.renderer import render_to_numpy, render_to_surface
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
