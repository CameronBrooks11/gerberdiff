from __future__ import annotations

import re
from pathlib import Path

from gerberdelta.types import (
    ApertureState,
    BoundingBox,
    CircleAperture,
    Diagnostic,
    DiagnosticSeverity,
    InterpolationMode,
    LayerState,
    Net,
    NetState,
    ParsedImage,
    UnitType,
)

# Pattern: optional sign, digits, optional decimal part  (e.g. 111.379 or -71.882)
_COORD_RE = re.compile(r"[XY]([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
_TOOL_DEF_RE = re.compile(r"T(\d+)C([\d.]+)", re.IGNORECASE)
_TOOL_SEL_RE = re.compile(r"^T(\d+)$", re.IGNORECASE)


def _to_inches(value: float, unit: UnitType) -> float:
    return value / 25.4 if unit == UnitType.Millimeter else value


def parse_excellon(content: str, source_path: Path | None = None) -> ParsedImage:
    """Parse an Excellon drill file into a ParsedImage.

    Tool definitions become ``CircleAperture`` entries in ``image.apertures``.
    Drill hits become ``Net(aperture_state=Flash)`` entries.
    All coordinates are normalised to inches.
    """
    lines = content.splitlines()

    # ---- mutable state ----
    unit: UnitType = UnitType.Millimeter  # will be set from header; default metric
    unit_seen: bool = False
    apertures: dict[int, CircleAperture] = {}
    nets: list[Net] = []
    bbox = BoundingBox()
    diagnostics: list[Diagnostic] = []
    current_tool: int = 0
    layer = LayerState()
    net_state = NetState()

    in_header: bool = False
    lineno: int = 0

    def warn(msg: str) -> None:
        diagnostics.append(Diagnostic(DiagnosticSeverity.Warning, msg, lineno))

    def parse_tool_def(line: str) -> None:
        m = _TOOL_DEF_RE.match(line)
        if m:
            tool_num = int(m.group(1))
            dia_raw = float(m.group(2))
            dia_in = _to_inches(dia_raw, unit)
            apertures[tool_num] = CircleAperture(diameter=dia_in)

    def parse_coord_line(line: str) -> None:
        nonlocal current_tool
        # Some generators include T<n> on the same line as XY
        tool_m = re.search(r"T(\d+)", line, re.IGNORECASE)
        if tool_m and not line.strip().upper().startswith("T"):
            current_tool = int(tool_m.group(1))

        # KiCad and most generators emit X then Y; some omit one or both
        x_val: float | None = None
        y_val: float | None = None
        for letter_match in re.finditer(r"([XY])([+-]?\d+(?:\.\d+)?)", line, re.IGNORECASE):
            letter = letter_match.group(1).upper()
            val = float(letter_match.group(2))
            if letter == "X":
                x_val = val
            elif letter == "Y":
                y_val = val

        if x_val is None and y_val is None:
            return
        if current_tool == 0:
            warn(f"Drill hit with no tool selected (line {lineno})")
            return

        x_in = _to_inches(x_val if x_val is not None else 0.0, unit)
        y_in = _to_inches(y_val if y_val is not None else 0.0, unit)

        nets.append(Net(
            start_x=x_in,
            start_y=y_in,
            stop_x=x_in,
            stop_y=y_in,
            aperture_index=current_tool,
            aperture_state=ApertureState.Flash,
            interpolation=InterpolationMode.Linear,
            layer_index=0,
            net_state_index=0,
        ))

        # Bounding box: expand by tool radius
        ap = apertures.get(current_tool)
        r = ap.diameter / 2.0 if ap is not None else 0.0
        bbox.expand(x_in, y_in, r)

    for lineno, raw_line in enumerate(lines, start=1):  # noqa: B007
        line = raw_line.strip()

        if not line or line.startswith(";"):
            continue  # blank or comment

        # ---- header start ----
        if line == "M48":
            in_header = True
            continue

        # ---- header end ----
        if in_header and line in ("%", "M95"):
            in_header = False
            continue

        if in_header:
            upper = line.upper()

            # Unit + zero omission
            if upper.startswith("METRIC"):
                unit = UnitType.Millimeter
                unit_seen = True
            elif upper.startswith("INCH"):
                unit = UnitType.Inch
                unit_seen = True
            elif upper.startswith("FMAT"):
                pass  # Excellon format version — informational
            # Tool definition in header
            elif _TOOL_DEF_RE.match(line):
                parse_tool_def(line)
            # Ignore all other header lines
            continue

        # ---- body ----
        upper = line.upper()

        # End-of-program codes
        if upper in ("M00", "M01", "M30"):
            break

        # G-codes
        if upper.startswith("G"):
            code = upper[1:3].lstrip("0") or "0"
            if code in ("0", "00", "5", "05", "90"):
                pass  # drill mode / absolute — ignore
            elif code in ("1", "01"):
                warn("G01 linear rout mode encountered (not drill)")
            elif code in ("2", "02", "3", "03"):
                warn("G02/G03 arc rout mode encountered (not drill)")
            # Other G codes ignored silently
            continue

        # M-codes in body (M71/M72 = metric/inch switches)
        if upper.startswith("M"):
            code_s = upper[1:].lstrip("0") or "0"
            if code_s == "71":
                unit = UnitType.Millimeter
            elif code_s == "72":
                unit = UnitType.Inch
            # M30 already handled above; ignore rest
            continue

        # Tool definition in body (some generators emit T<n>C<dia> here)
        if _TOOL_DEF_RE.match(line):
            parse_tool_def(line)
            continue

        # Tool select: bare T<n>
        m = _TOOL_SEL_RE.match(line)
        if m:
            current_tool = int(m.group(1))
            continue

        # Coordinate line
        if re.search(r"[XY]", line, re.IGNORECASE):
            parse_coord_line(line)
            continue

        # Anything else: ignore silently (R-codes, comments without ';', etc.)

    if not unit_seen:
        diagnostics.append(Diagnostic(
            DiagnosticSeverity.Warning,
            "No unit declaration found; defaulting to METRIC",
            None,
        ))

    return ParsedImage(
        nets=nets,
        apertures=dict(apertures),
        layers=[layer],
        net_states=[net_state],
        bounding_box=bbox,
        diagnostics=diagnostics,
        source_path=source_path,
    )
