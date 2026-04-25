__version__ = "0.24.0"

from gerberdelta.diff.diff_engine import SingleLayerDiff, compute_diff, compute_full_diff
from gerberdelta.diff.layer_matcher import LayerPair, match_layers
from gerberdelta.parse.excellon_parser import parse_excellon
from gerberdelta.parse.gerber_state import parse_gerber
from gerberdelta.render.renderer import render_to_numpy, render_to_surface
from gerberdelta.render.viewport import Viewport, compute_viewport
from gerberdelta.types import (
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
    # Version
    "__version__",
    # Parse
    "parse_gerber",
    "parse_excellon",
    # Render
    "render_to_numpy",
    "render_to_surface",
    "Viewport",
    "compute_viewport",
    # Diff
    "compute_diff",
    "compute_full_diff",
    "SingleLayerDiff",
    # Layer matching
    "match_layers",
    "LayerPair",
    # Core IR types
    "ParsedImage",
    "BoundingBox",
    "RegionFill",
    # Diff result types
    "DiffResult",
    "LayerDiffResult",
    "Region",
    # Enums
    "DiagnosticSeverity",
    "LayerType",
    "LayerStatus",
    # Diagnostics
    "Diagnostic",
    # Exceptions
    "GerberParseError",
]
