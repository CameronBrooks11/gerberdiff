from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    # MacroDef lives in parse/macro_parser.py (Phase 4).  Imported only for
    # type-checking to avoid a runtime circular dependency.
    from gerberdiff.parse.macro_parser import MacroDef


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ApertureType(StrEnum):
    Circle = "circle"
    Rectangle = "rectangle"
    Obround = "obround"
    Polygon = "polygon"
    Macro = "macro"
    Block = "block"


class ApertureState(StrEnum):
    Off = "off"
    On = "on"
    Flash = "flash"


class InterpolationMode(StrEnum):
    Linear = "linear"
    ClockwiseCircular = "cw"
    CounterClockwiseCircular = "ccw"


class Polarity(StrEnum):
    Dark = "dark"
    Clear = "clear"


class MirrorState(StrEnum):
    # None_ avoids collision with the Python builtin None
    None_ = "none"
    FlipA = "flipA"
    FlipB = "flipB"
    FlipAB = "flipAB"


class UnitType(StrEnum):
    Inch = "inch"
    Millimeter = "mm"


class ZeroOmission(StrEnum):
    Leading = "leading"  # leading zeros omitted (most common, RS-274X default)
    Trailing = "trailing"  # trailing zeros omitted
    Explicit = "explicit"  # all digits present (rare)


class CoordinateMode(StrEnum):
    Absolute = "absolute"
    Incremental = "incremental"


class DiagnosticSeverity(StrEnum):
    Error = "error"  # abort: parse result is unusable
    Warning = "warning"  # proceed: result may be degraded
    Info = "info"  # informational, suppressed unless -v


class LayerStatus(StrEnum):
    Matched = "matched"
    Added = "added"
    Removed = "removed"


class LayerType(StrEnum):
    FCu = "FCu"
    BCu = "BCu"
    InCu = "InCu"
    FMask = "FMask"
    BMask = "BMask"
    FPaste = "FPaste"
    BPaste = "BPaste"
    FSilk = "FSilk"
    BSilk = "BSilk"
    EdgeCuts = "EdgeCuts"
    NPTH = "NPTH"
    PTH = "PTH"
    Drill = "Drill"
    Unknown = "Unknown"


# ---------------------------------------------------------------------------
# Geometric primitives
# ---------------------------------------------------------------------------


@dataclass
class ArcSegment:
    """Fully resolved arc geometry.  Angles in degrees."""

    center_x: float
    center_y: float
    radius: float
    start_angle_deg: float
    end_angle_deg: float


@dataclass
class BoundingBox:
    """Axis-aligned bounding box.  All values in inches.

    Initialises to the sentinel state {+inf, +inf, -inf, -inf} so that the
    first call to expand() sets the box correctly.  Check is_valid before use.
    """

    # math.inf is an immutable float constant -- field(default=...) is correct.
    min_x: float = field(default=math.inf)
    min_y: float = field(default=math.inf)
    max_x: float = field(default=-math.inf)
    max_y: float = field(default=-math.inf)

    @property
    def is_valid(self) -> bool:
        """True if at least one point has been added."""
        return math.isfinite(self.min_x)

    def expand(self, x: float, y: float, radius: float = 0.0) -> None:
        """Expand to include the point (x+/-radius, y+/-radius)."""
        self.min_x = min(self.min_x, x - radius)
        self.min_y = min(self.min_y, y - radius)
        self.max_x = max(self.max_x, x + radius)
        self.max_y = max(self.max_y, y + radius)


# ---------------------------------------------------------------------------
# Step-and-repeat / layer / net state
# ---------------------------------------------------------------------------


@dataclass
class StepAndRepeat:
    x: int = 1  # repeat count X (>=1)
    y: int = 1  # repeat count Y (>=1)
    dist_x: float = 0.0  # step distance X in inches
    dist_y: float = 0.0  # step distance Y in inches


@dataclass
class LayerState:
    polarity: Polarity = Polarity.Dark
    rotation: float = 0.0
    mirror: MirrorState = MirrorState.None_
    scale: float = 1.0
    step_and_repeat: StepAndRepeat = field(default_factory=StepAndRepeat)
    name: str | None = None


@dataclass
class CoordState:
    """Snapshot of global image-level state at the time a net was emitted.

    ``unit`` is stored for diagnostic/display purposes only.  All coordinates
    in DrawOp are already normalised to inches by convert_coordinate at parse
    time.  The deprecated RS-274X image/axis commands (%MI%, %AS%, %OF%,
    %SF%) are silently ignored by the parser; their fields have been removed
    from this type.
    """

    unit: UnitType = UnitType.Inch


@dataclass
class DrawOp:
    """A single drawing operation.  All coordinates in inches."""

    start_x: float
    start_y: float
    stop_x: float
    stop_y: float
    aperture_index: int
    aperture_state: ApertureState
    interpolation: InterpolationMode
    layer_index: int
    net_state_index: int
    arc_segment: ArcSegment | None = None
    attributes: dict[str, str] | None = None  # %TO.* object attributes


@dataclass
class RegionFill:
    """A filled region produced by a G36..G37 block.

    ``segments`` are the ``DrawOp`` objects from inside the region (G36/G37
    are not included).  All coordinates in inches.
    """

    layer_index: int
    net_state_index: int
    segments: list[DrawOp]


@dataclass
class Diagnostic:
    severity: DiagnosticSeverity
    message: str
    line: int | None = None


# ---------------------------------------------------------------------------
# Aperture definitions
# ---------------------------------------------------------------------------


@dataclass
class CircleAperture:
    aperture_type: Literal[ApertureType.Circle] = ApertureType.Circle
    diameter: float = 0.0  # inches
    hole_diameter: float | None = None


@dataclass
class RectangleAperture:
    aperture_type: Literal[ApertureType.Rectangle] = ApertureType.Rectangle
    width: float = 0.0
    height: float = 0.0
    hole_diameter: float | None = None


@dataclass
class ObroundAperture:
    aperture_type: Literal[ApertureType.Obround] = ApertureType.Obround
    width: float = 0.0
    height: float = 0.0
    hole_diameter: float | None = None


@dataclass
class PolygonAperture:
    aperture_type: Literal[ApertureType.Polygon] = ApertureType.Polygon
    outer_diameter: float = 0.0
    num_vertices: int = 4
    rotation: float = 0.0
    hole_diameter: float | None = None


@dataclass
class MacroAperture:
    aperture_type: Literal[ApertureType.Macro] = ApertureType.Macro
    macro_def: MacroDef | None = None  # defined in parse/macro_parser.py (Phase 4)
    params: list[float] = field(default_factory=list)
    unit_scale: float = 1.0  # 1.0 for inch files; 1/25.4 for mm files


@dataclass
class BlockAperture:
    aperture_type: Literal[ApertureType.Block] = ApertureType.Block
    draw_ops: list[DrawOp | RegionFill] = field(default_factory=list)
    apertures: dict[int, Aperture] = field(default_factory=dict)
    layers: list[LayerState] = field(default_factory=list)
    bounding_box: BoundingBox = field(default_factory=BoundingBox)


# Union type alias -- used for aperture dict values and type-narrowing dispatch.
Aperture: TypeAlias = (
    CircleAperture
    | RectangleAperture
    | ObroundAperture
    | PolygonAperture
    | MacroAperture
    | BlockAperture
)


# ---------------------------------------------------------------------------
# Top-level IR output
# ---------------------------------------------------------------------------


@dataclass
class ParsedImage:
    """The complete output of parsing one Gerber or Excellon file."""

    draw_ops: list[DrawOp | RegionFill]
    apertures: dict[int, Aperture]  # D-code -> aperture
    layers: list[LayerState]
    coord_states: list[CoordState]
    bounding_box: BoundingBox
    diagnostics: list[Diagnostic]
    source_path: Path | None = None


# ---------------------------------------------------------------------------
# Diff result types
# ---------------------------------------------------------------------------


@dataclass
class Region:
    """A contiguous changed area.  Coordinates in inches."""

    id: int
    centroid_x: float
    centroid_y: float
    bounding_box: BoundingBox  # consistent naming with ParsedImage, BlockAperture
    pixel_count: int


@dataclass
class LayerDiffResult:
    name: str
    status: LayerStatus  # matched | added | removed
    layer_type: LayerType
    changed_pixel_count: int
    total_pixel_count: int
    regions: list[Region]

    @property
    def changed_fraction(self) -> float:
        if self.total_pixel_count == 0:
            return 0.0
        return self.changed_pixel_count / self.total_pixel_count


@dataclass
class DiffResult:
    layers: list[LayerDiffResult]

    @property
    def has_changes(self) -> bool:
        """True when any layer was added, removed, or has changed pixels."""
        return any(
            lr.changed_pixel_count > 0 or lr.status != LayerStatus.Matched for lr in self.layers
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GerberParseError(Exception):
    """Raised by ``compute_full_diff`` when a fatal parse error is encountered.

    Attributes
    ----------
    path : Path
        The file that triggered the error.
    """

    def __init__(self, path: Path, message: str, line: int | None = None) -> None:
        self.path = path
        loc = f" (line {line})" if line is not None else ""
        super().__init__(f"{path.name}: {message}{loc}")
