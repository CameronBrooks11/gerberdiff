from __future__ import annotations

from pathlib import Path

from gerberdelta.parse.arc_math import compute_arc_multi_quadrant, compute_arc_single_quadrant
from gerberdelta.parse.gerber_parser import (
    FormatStatement,
    convert_coordinate,
    parse_aperture_definition,
    parse_format_statement,
)
from gerberdelta.parse.macro_parser import MacroDef, parse_macro_body
from gerberdelta.parse.tokenizer import TokenType, tokenize_gerber
from gerberdelta.types import (
    Aperture,
    ApertureState,
    BoundingBox,
    CircleAperture,
    CoordinateMode,
    Diagnostic,
    DiagnosticSeverity,
    InterpolationMode,
    LayerState,
    MirrorState,
    Net,
    NetState,
    ObroundAperture,
    ParsedImage,
    Polarity,
    PolygonAperture,
    RectangleAperture,
    StepAndRepeat,
    UnitType,
    ZeroOmission,
)

# Default format statement used when no %FS...% is present in the file.
# FSLAX25Y25 is the most common real-world default.
_DEFAULT_FORMAT = FormatStatement(
    zero_omission=ZeroOmission.Leading,
    coordinate_mode=CoordinateMode.Absolute,
    x_integer=2,
    x_decimal=5,
    y_integer=2,
    y_decimal=5,
)

# Two-character prefix strings that begin a top-level extended command.
# Any EXTENDED token whose prefix is NOT in this set, when we're inside a
# macro definition, is treated as a macro body line.
_COMMAND_PREFIXES: frozenset[str] = frozenset(
    [
        "FS", "MO", "AD", "AM", "LP", "LM", "LR", "LS", "LN",
        "SR", "AB", "TO", "TA", "TD", "TF", "IA", "AS", "MI", "OF", "SF",
    ]
)


# ---------------------------------------------------------------------------
# Internal parser class
# ---------------------------------------------------------------------------


class _GerberParser:
    """Stateful RS-274X parser.  Instantiate once per file; call parse()."""

    def __init__(self, source_path: Path | None) -> None:
        # ---- accumulated output ----
        self._fmt: FormatStatement = _DEFAULT_FORMAT
        self._fmt_seen: bool = False
        self._apertures: dict[int, Aperture] = {}
        self._nets: list[Net] = []
        self._layers: list[LayerState] = [LayerState()]
        self._net_states: list[NetState] = [NetState()]
        self._bbox: BoundingBox = BoundingBox()
        self._diagnostics: list[Diagnostic] = []
        self._source_path = source_path

        # ---- drawing cursor ----
        self._prev_x: float = 0.0
        self._prev_y: float = 0.0

        # per-block raw coordinate storage (reset each END_OF_BLOCK)
        self._raw_x_int: int = 0
        self._raw_x_str: str = "0"
        self._raw_y_int: int = 0
        self._raw_y_str: str = "0"
        self._raw_i_int: int = 0
        self._raw_i_str: str = "0"
        self._raw_j_int: int = 0
        self._raw_j_str: str = "0"
        self._x_in_block: bool = False
        self._y_in_block: bool = False
        self._i_in_block: bool = False
        self._j_in_block: bool = False
        self._coord_changed: bool = False

        # ---- drawing state ----
        self._current_aperture: int = 0
        self._aperture_state: ApertureState = ApertureState.Off
        self._interpolation: InterpolationMode = InterpolationMode.Linear
        self._multi_quadrant: bool = False
        self._in_region_fill: bool = False
        self._current_layer_idx: int = 0
        self._current_net_state_idx: int = 0
        self._unit: UnitType = UnitType.Inch
        self._done: bool = False

        # ---- macro assembly ----
        self._macro_map: dict[str, MacroDef] = {}
        self._macro_name: str | None = None
        self._macro_lines: list[str] = []

        # ---- object / aperture attributes ----
        self._net_attrs: dict[str, str] = {}
        self._aperture_attrs: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _warn(self, msg: str, line: int | None = None) -> None:
        self._diagnostics.append(Diagnostic(DiagnosticSeverity.Warning, msg, line))

    def _info(self, msg: str, line: int | None = None) -> None:
        self._diagnostics.append(Diagnostic(DiagnosticSeverity.Info, msg, line))

    def _current_layer(self) -> LayerState:
        return self._layers[self._current_layer_idx]

    def _convert_x(self, raw_int: int, raw_str: str) -> float:
        return convert_coordinate(
            raw_int, raw_str,
            self._fmt.x_integer, self._fmt.x_decimal,
            self._fmt.zero_omission, self._unit,
        )

    def _convert_y(self, raw_int: int, raw_str: str) -> float:
        return convert_coordinate(
            raw_int, raw_str,
            self._fmt.y_integer, self._fmt.y_decimal,
            self._fmt.zero_omission, self._unit,
        )

    def _aperture_radius(self) -> float:
        ap = self._apertures.get(self._current_aperture)
        if ap is None:
            return 0.0
        if isinstance(ap, CircleAperture):
            return ap.diameter / 2.0
        if isinstance(ap, (RectangleAperture, ObroundAperture)):
            return max(ap.width, ap.height) / 2.0
        if isinstance(ap, PolygonAperture):
            return ap.outer_diameter / 2.0
        # MacroAperture, BlockAperture: conservative — renderer computes exact bbox
        return 0.0

    def _flush_macro(self) -> None:
        if self._macro_name is None:
            return
        body = "*".join(self._macro_lines)
        try:
            mdef = parse_macro_body(self._macro_name, body)
            self._macro_map[self._macro_name] = mdef
        except Exception as exc:  # pragma: no cover
            self._warn(f"Macro parse failed for {self._macro_name!r}: {exc}")
        self._macro_name = None
        self._macro_lines = []

    def _reset_block(self) -> None:
        """Reset per-block state after END_OF_BLOCK."""
        self._x_in_block = False
        self._y_in_block = False
        self._i_in_block = False
        self._j_in_block = False
        self._coord_changed = False

    # ------------------------------------------------------------------
    # Net emission
    # ------------------------------------------------------------------

    def _emit_net(self) -> None:
        fmt = self._fmt

        # Resolve stop position (use prev if coordinate not updated this block)
        if self._x_in_block:
            stop_x = self._convert_x(self._raw_x_int, self._raw_x_str)
            if fmt.coordinate_mode == CoordinateMode.Incremental:
                stop_x += self._prev_x
        else:
            stop_x = self._prev_x

        if self._y_in_block:
            stop_y = self._convert_y(self._raw_y_int, self._raw_y_str)
            if fmt.coordinate_mode == CoordinateMode.Incremental:
                stop_y += self._prev_y
        else:
            stop_y = self._prev_y

        # Arc centre offsets (I uses X format, J uses Y format per RS-274X spec)
        arc_i = self._convert_x(self._raw_i_int, self._raw_i_str) if self._i_in_block else 0.0
        arc_j = self._convert_y(self._raw_j_int, self._raw_j_str) if self._j_in_block else 0.0

        # Compute arc geometry when drawing in arc mode
        arc_segment = None
        if self._aperture_state == ApertureState.On and self._interpolation in (
            InterpolationMode.ClockwiseCircular,
            InterpolationMode.CounterClockwiseCircular,
        ):
            clockwise = self._interpolation == InterpolationMode.ClockwiseCircular
            if self._multi_quadrant:
                arc_segment = compute_arc_multi_quadrant(
                    self._prev_x, self._prev_y, stop_x, stop_y, arc_i, arc_j, clockwise,
                )
            else:
                arc_segment = compute_arc_single_quadrant(
                    self._prev_x, self._prev_y, stop_x, stop_y, arc_i, arc_j, clockwise,
                )

        net = Net(
            start_x=self._prev_x,
            start_y=self._prev_y,
            stop_x=stop_x,
            stop_y=stop_y,
            aperture_index=self._current_aperture,
            aperture_state=self._aperture_state,
            interpolation=self._interpolation,
            layer_index=self._current_layer_idx,
            net_state_index=self._current_net_state_idx,
            arc_segment=arc_segment,
            attributes=dict(self._net_attrs) if self._net_attrs else None,
        )
        self._nets.append(net)

        # Expand bounding box
        r = self._aperture_radius()
        self._bbox.expand(stop_x, stop_y, r)
        if self._aperture_state == ApertureState.On:
            self._bbox.expand(self._prev_x, self._prev_y, r)

        self._prev_x = stop_x
        self._prev_y = stop_y

    # ------------------------------------------------------------------
    # Token handlers
    # ------------------------------------------------------------------

    def _handle_g_code(self, value: int, line: int) -> None:
        if value == 1:
            self._interpolation = InterpolationMode.Linear
        elif value == 2:
            self._interpolation = InterpolationMode.ClockwiseCircular
        elif value == 3:
            self._interpolation = InterpolationMode.CounterClockwiseCircular
        elif value == 36:
            self._in_region_fill = True
            self._nets.append(Net(
                start_x=self._prev_x, start_y=self._prev_y,
                stop_x=self._prev_x, stop_y=self._prev_y,
                aperture_index=self._current_aperture,
                aperture_state=ApertureState.Off,
                interpolation=InterpolationMode.RegionStart,
                layer_index=self._current_layer_idx,
                net_state_index=self._current_net_state_idx,
            ))
        elif value == 37:
            self._in_region_fill = False
            self._nets.append(Net(
                start_x=self._prev_x, start_y=self._prev_y,
                stop_x=self._prev_x, stop_y=self._prev_y,
                aperture_index=self._current_aperture,
                aperture_state=ApertureState.Off,
                interpolation=InterpolationMode.RegionEnd,
                layer_index=self._current_layer_idx,
                net_state_index=self._current_net_state_idx,
            ))
        elif value in (54, 55, 70, 71):
            # 54/55: deprecated aperture select/flash — ignore
            # 70/71: deprecated inch/mm (should use MO instead) — update unit
            if value == 70:
                self._unit = UnitType.Inch
            elif value == 71:
                self._unit = UnitType.Millimeter
        elif value == 74:
            self._multi_quadrant = False
        elif value == 75:
            self._multi_quadrant = True
        elif value == 90:
            self._fmt = FormatStatement(
                zero_omission=self._fmt.zero_omission,
                coordinate_mode=CoordinateMode.Absolute,
                x_integer=self._fmt.x_integer,
                x_decimal=self._fmt.x_decimal,
                y_integer=self._fmt.y_integer,
                y_decimal=self._fmt.y_decimal,
            )
        elif value == 91:
            self._fmt = FormatStatement(
                zero_omission=self._fmt.zero_omission,
                coordinate_mode=CoordinateMode.Incremental,
                x_integer=self._fmt.x_integer,
                x_decimal=self._fmt.x_decimal,
                y_integer=self._fmt.y_integer,
                y_decimal=self._fmt.y_decimal,
            )
        else:
            self._warn(f"Unknown G code G{value:02d}", line)

    def _handle_d_code(self, value: int, line: int) -> None:
        if value == 1:
            self._aperture_state = ApertureState.On
            self._coord_changed = True
        elif value == 2:
            self._aperture_state = ApertureState.Off
            self._coord_changed = True
        elif value == 3:
            self._aperture_state = ApertureState.Flash
            self._coord_changed = True
        elif value >= 10:
            self._current_aperture = value
        else:
            self._warn(f"Unknown D code D{value:02d}", line)

    def _handle_extended(self, body: str, line: int) -> None:
        prefix = body[:2].upper()

        # When accumulating a macro body, all unrecognised token bodies are
        # macro primitive / assignment lines.  Any top-level command ends it.
        if self._macro_name is not None:
            if prefix not in _COMMAND_PREFIXES:
                self._macro_lines.append(body)
                return
            # Recognised command — flush macro first, then dispatch normally
            self._flush_macro()

        if prefix == "FS":
            fs = parse_format_statement(body)
            if fs is None:
                self._warn(f"Could not parse format statement: {body!r}", line)
            else:
                self._fmt = fs
                self._fmt_seen = True

        elif prefix == "MO":
            code = body[2:4].upper()
            if code == "IN":
                self._unit = UnitType.Inch
            elif code == "MM":
                self._unit = UnitType.Millimeter
            # Push a NetState capturing the unit change
            self._net_states.append(NetState(unit=self._unit))
            self._current_net_state_idx = len(self._net_states) - 1

        elif prefix == "AD":
            result = parse_aperture_definition(body, self._unit, self._macro_map)
            if result is None:
                self._warn(f"Could not parse aperture definition: {body!r}", line)
            else:
                d_code, aperture = result
                self._apertures[d_code] = aperture
                self._aperture_attrs = {}  # aperture attributes consumed

        elif prefix == "AM":
            # Start a new macro definition
            name = body[2:].strip()
            if name:
                self._macro_name = name
                self._macro_lines = []

        elif prefix == "LP":
            code = body[2:3].upper()
            polarity = Polarity.Clear if code == "C" else Polarity.Dark
            prev = self._current_layer()
            new_layer = LayerState(
                polarity=polarity,
                rotation=prev.rotation,
                mirror=prev.mirror,
                scale=prev.scale,
                name=prev.name,
            )
            self._layers.append(new_layer)
            self._current_layer_idx = len(self._layers) - 1

        elif prefix == "LM":
            code = body[2:].strip().upper()
            mirror = {
                "N": MirrorState.None_,
                "X": MirrorState.FlipA,
                "Y": MirrorState.FlipB,
                "XY": MirrorState.FlipAB,
            }.get(code, MirrorState.None_)
            self._current_layer().mirror = mirror

        elif prefix == "LR":
            try:
                self._current_layer().rotation = float(body[2:])
            except ValueError:
                self._warn(f"Invalid LR value: {body!r}", line)

        elif prefix == "LS":
            try:
                self._current_layer().scale = float(body[2:])
            except ValueError:
                self._warn(f"Invalid LS value: {body!r}", line)

        elif prefix == "LN":
            self._current_layer().name = body[2:]

        elif prefix == "SR":
            self._handle_sr(body[2:], line)

        elif prefix == "AB":
            pass  # Block aperture open/close — deferred to Phase 14

        elif prefix == "TO":
            # Object attribute: %TO.<name>,<value>*%
            rest = body[2:]
            if rest.startswith("."):
                comma = rest.find(",")
                if comma > 0:
                    self._net_attrs[rest[1:comma]] = rest[comma + 1:]

        elif prefix == "TA":
            # Aperture attribute
            rest = body[2:]
            if rest.startswith("."):
                comma = rest.find(",")
                if comma > 0:
                    self._aperture_attrs[rest[1:comma]] = rest[comma + 1:]

        elif prefix == "TD":
            # Delete attribute(s)
            name = body[2:].strip()
            if name:
                self._net_attrs.pop(name.lstrip("."), None)
                self._aperture_attrs.pop(name.lstrip("."), None)
            else:
                self._net_attrs.clear()
                self._aperture_attrs.clear()

        elif prefix == "TF":
            pass  # File attribute — informational, ignored

        elif prefix in ("IA", "AS", "MI", "OF", "SF"):
            pass  # Deprecated image/axis attributes — safely ignored

        else:
            self._warn(f"Unknown extended command prefix {prefix!r}", line)

    def _handle_sr(self, params: str, line: int) -> None:
        """Handle the SR body after stripping the 'SR' prefix."""
        if not params.strip():
            # Close SR block — push a fresh default layer
            self._layers.append(LayerState())
            self._current_layer_idx = len(self._layers) - 1
            return

        # Parse SRX<count>Y<count>I<step>J<step>
        x_count = y_count = 1
        step_x = step_y = 0.0
        s = params.strip()
        pos = 0
        while pos < len(s):
            letter = s[pos].upper()
            if letter not in "XYIJ":
                pos += 1
                continue
            pos += 1
            j = pos
            while j < len(s) and s[j] not in "XYIJxyij":
                j += 1
            try:
                val = float(s[pos:j])
                if letter == "X":
                    x_count = max(1, int(val))
                elif letter == "Y":
                    y_count = max(1, int(val))
                elif letter == "I":
                    step_x = val / 25.4 if self._unit == UnitType.Millimeter else val
                elif letter == "J":
                    step_y = val / 25.4 if self._unit == UnitType.Millimeter else val
            except ValueError:
                self._warn(f"Invalid SR parameter {letter}={s[pos:j]!r}", line)
            pos = j

        self._current_layer().step_and_repeat = StepAndRepeat(
            x=x_count, y=y_count, dist_x=step_x, dist_y=step_y,
        )

    # ------------------------------------------------------------------
    # Main parse loop
    # ------------------------------------------------------------------

    def parse(self, content: str) -> ParsedImage:
        for token in tokenize_gerber(content):
            if self._done:
                break
            tt = token.type
            line = token.line

            if tt == TokenType.G:
                if isinstance(token.value, int):
                    self._handle_g_code(token.value, line)

            elif tt == TokenType.D:
                if isinstance(token.value, int):
                    self._handle_d_code(token.value, line)

            elif tt == TokenType.M:
                if isinstance(token.value, int) and token.value == 2:
                    self._done = True
                    break

            elif tt == TokenType.X:
                if isinstance(token.value, int):
                    self._raw_x_int = token.value
                    self._raw_x_str = token.raw or str(token.value)
                    self._x_in_block = True
                    self._coord_changed = True

            elif tt == TokenType.Y:
                if isinstance(token.value, int):
                    self._raw_y_int = token.value
                    self._raw_y_str = token.raw or str(token.value)
                    self._y_in_block = True
                    self._coord_changed = True

            elif tt == TokenType.I:
                if isinstance(token.value, int):
                    self._raw_i_int = token.value
                    self._raw_i_str = token.raw or str(token.value)
                    self._i_in_block = True

            elif tt == TokenType.J:
                if isinstance(token.value, int):
                    self._raw_j_int = token.value
                    self._raw_j_str = token.raw or str(token.value)
                    self._j_in_block = True

            elif tt == TokenType.END_OF_BLOCK:
                if self._coord_changed:
                    self._emit_net()
                self._reset_block()

            elif tt == TokenType.EXTENDED:
                if isinstance(token.value, str):
                    self._handle_extended(token.value, line)

            elif tt == TokenType.EOF:
                if self._in_region_fill:
                    self._warn("Region fill not closed at end of file", line)
                break

        # Final cleanup
        self._flush_macro()

        if not self._fmt_seen:
            self._info("No format statement found; using default FSLAX25Y25")

        return ParsedImage(
            nets=self._nets,
            apertures=self._apertures,
            layers=self._layers,
            net_states=self._net_states,
            bounding_box=self._bbox,
            diagnostics=self._diagnostics,
            source_path=self._source_path,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_gerber(content: str, source_path: Path | None = None) -> ParsedImage:
    """Parse a Gerber RS-274X file string into a ParsedImage.

    All diagnostics (errors, warnings, info) are collected on
    ``image.diagnostics``.  This function never raises for parse-level
    problems; only genuine Python-level exceptions (e.g. MemoryError) propagate.
    """
    return _GerberParser(source_path).parse(content)
