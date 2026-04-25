from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gerberdiff.types import (
    ApertureState,
    BoundingBox,
    CircleAperture,
    CoordState,
    Diagnostic,
    DiagnosticSeverity,
    DrawOp,
    InterpolationMode,
    LayerState,
    ParsedImage,
    RegionFill,
    UnitType,
)

_TOOL_DEF_RE = re.compile(r"T(\d+)C([\d.]+)", re.IGNORECASE)
_TOOL_SEL_RE = re.compile(r"^T(\d+)$", re.IGNORECASE)
# Matches explicit digit-count specifiers, e.g. "000.000" or "0000.0000"
_FORMAT_DIGITS_RE = re.compile(r"(\d+)\.(\d+)")


@dataclass
class _FormatSpec:
    """Excellon coordinate-format specification."""

    unit: UnitType
    zero_suppression: str  # "LZ" (leading zeros suppressed) or "TZ" (trailing zeros suppressed)
    integer_digits: int  # digits before the implied decimal point
    decimal_digits: int  # digits after the implied decimal point


def _parse_unit_line(upper: str) -> _FormatSpec:
    """Parse a METRIC or INCH header line into a _FormatSpec.

    Handles the unit keyword (``METRIC`` / ``INCH``), zero-suppression keyword
    (``,LZ`` / ``,TZ``), and optional explicit digit counts expressed as a
    dot-delimited pattern such as ``,000.000`` (3 integer + 3 decimal digits).
    """
    if upper.startswith("METRIC"):
        unit = UnitType.Millimeter
        int_d, dec_d = 3, 3
    else:  # INCH
        unit = UnitType.Inch
        int_d, dec_d = 2, 4

    zs = "LZ" if ",LZ" in upper else "TZ"

    m = _FORMAT_DIGITS_RE.search(upper)
    if m:
        int_d = len(m.group(1))
        dec_d = len(m.group(2))

    return _FormatSpec(unit=unit, zero_suppression=zs, integer_digits=int_d, decimal_digits=dec_d)


def _apply_format(raw: str, spec: _FormatSpec) -> tuple[float, bool]:
    """Convert a raw coordinate token to a float in *spec.unit*'s native units.

    If the token contains a decimal point it is used directly (KiCad modern
    output and any explicit-decimal generator).  Otherwise the integer string
    is padded according to the zero-suppression convention and the decimal
    point is inserted at the configured position.

    Returns a ``(value, truncated)`` pair.  *truncated* is ``True`` when the
    input had more digits than the format allows; callers should emit a
    diagnostic warning in that case.
    """
    if "." in raw:
        return float(raw), False

    total = spec.integer_digits + spec.decimal_digits
    sign = ""
    digits = raw
    if raw and raw[0] in ("+", "-"):
        sign = raw[0]
        digits = raw[1:]

    truncated = len(digits) > total

    if spec.zero_suppression == "TZ":
        # Trailing zeros suppressed in file → right-pad to restore them
        digits = digits.ljust(total, "0")
    else:
        # Leading zeros suppressed in file (LZ) → left-pad to restore them
        digits = digits.zfill(total)

    if truncated:
        digits = digits[:total]

    if spec.decimal_digits > 0:
        int_part = digits[: -spec.decimal_digits] or "0"
        dec_part = digits[-spec.decimal_digits :]
        return float(f"{sign}{int_part}.{dec_part}"), truncated
    return float(f"{sign}{digits}"), truncated


def _to_inches(value: float, unit: UnitType) -> float:
    return value / 25.4 if unit == UnitType.Millimeter else value


def _parse_tool_def(
    line: str,
    format_spec: _FormatSpec,
    apertures: dict[int, CircleAperture],
) -> None:
    """Parse a tool-definition line (``T<n>C<dia>``) and record it in *apertures*."""
    m = _TOOL_DEF_RE.match(line)
    if m:
        tool_num = int(m.group(1))
        dia_raw = float(m.group(2))
        dia_in = _to_inches(dia_raw, format_spec.unit)
        apertures[tool_num] = CircleAperture(diameter=dia_in)


def _parse_coord_line(
    line: str,
    format_spec: _FormatSpec,
    current_tool: int,
    apertures: dict[int, CircleAperture],
    nets: list[DrawOp | RegionFill],
    bbox: BoundingBox,
    diagnostics: list[Diagnostic],
    lineno: int,
) -> int:
    """Parse a coordinate line and append a flash DrawOp.

    Returns the (possibly updated) current tool number.
    """
    # Some generators include T<n> on the same line as XY
    tool_m = re.search(r"T(\d+)", line, re.IGNORECASE)
    if tool_m and not line.strip().upper().startswith("T"):
        current_tool = int(tool_m.group(1))

    x_val: float | None = None
    y_val: float | None = None
    for letter_match in re.finditer(r"([XY])([+-]?\d+(?:\.\d+)?)", line, re.IGNORECASE):
        letter = letter_match.group(1).upper()
        val, truncated = _apply_format(letter_match.group(2), format_spec)
        if truncated:
            diagnostics.append(
                Diagnostic(
                    DiagnosticSeverity.Warning,
                    f"Coordinate field has more digits than format allows; truncated (line {lineno})",
                    lineno,
                )
            )
        if letter == "X":
            x_val = val
        elif letter == "Y":
            y_val = val

    if x_val is None and y_val is None:
        return current_tool
    if current_tool == 0:
        diagnostics.append(
            Diagnostic(
                DiagnosticSeverity.Warning,
                f"Drill hit with no tool selected (line {lineno})",
                lineno,
            )
        )
        return current_tool

    x_in = _to_inches(x_val if x_val is not None else 0.0, format_spec.unit)
    y_in = _to_inches(y_val if y_val is not None else 0.0, format_spec.unit)

    nets.append(
        DrawOp(
            start_x=x_in,
            start_y=y_in,
            stop_x=x_in,
            stop_y=y_in,
            aperture_index=current_tool,
            aperture_state=ApertureState.Flash,
            interpolation=InterpolationMode.Linear,
            layer_index=0,
            net_state_index=0,
        )
    )

    ap = apertures.get(current_tool)
    r = ap.diameter / 2.0 if ap is not None else 0.0
    bbox.expand(x_in, y_in, r)

    return current_tool


def parse_excellon(content: str, source_path: Path | None = None) -> ParsedImage:
    """Parse an Excellon drill file into a ParsedImage.

    Tool definitions become ``CircleAperture`` entries in ``image.apertures``.
    Drill hits become ``DrawOp(aperture_state=Flash)`` entries.
    All coordinates are normalised to inches.

    Both decimal-format (KiCad modern) and integer-format (Altium, older KiCad,
    most CAM systems) coordinate encodings are supported.  The zero-suppression
    convention and digit counts are read from the ``METRIC``/``INCH`` header
    line.  If no format header is present, ``METRIC,TZ`` with 3.3 digit counts
    is assumed and a ``DiagnosticSeverity.Warning`` is emitted.
    """
    lines = content.splitlines()

    # ---- mutable state ----
    # Default: METRIC,TZ 3.3; overwritten when the header declares a format.
    format_spec = _FormatSpec(
        unit=UnitType.Millimeter,
        zero_suppression="TZ",
        integer_digits=3,
        decimal_digits=3,
    )
    format_seen: bool = False
    apertures: dict[int, CircleAperture] = {}
    nets: list[DrawOp | RegionFill] = []
    bbox = BoundingBox()
    diagnostics: list[Diagnostic] = []
    current_tool: int = 0
    layer = LayerState()
    net_state = CoordState()

    in_header: bool = False
    lineno: int = 0

    for lineno, raw_line in enumerate(lines, start=1):
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

            # Unit + zero-suppression + optional digit-count
            if upper.startswith("METRIC") or upper.startswith("INCH"):
                format_spec = _parse_unit_line(upper)
                format_seen = True
            elif upper.startswith("FMAT"):
                pass  # Excellon format version -- informational
            # Tool definition in header
            elif _TOOL_DEF_RE.match(line):
                _parse_tool_def(line, format_spec, apertures)
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
                pass  # drill mode / absolute -- ignore
            elif code in ("1", "01"):
                diagnostics.append(
                    Diagnostic(
                        DiagnosticSeverity.Warning,
                        "G01 linear rout mode encountered (not drill)",
                        lineno,
                    )
                )
            elif code in ("2", "02", "3", "03"):
                diagnostics.append(
                    Diagnostic(
                        DiagnosticSeverity.Warning,
                        "G02/G03 arc rout mode encountered (not drill)",
                        lineno,
                    )
                )
            # Other G codes ignored silently
            continue

        # M-codes in body (M71/M72 = metric/inch switches)
        if upper.startswith("M"):
            code_s = upper[1:].lstrip("0") or "0"
            if code_s == "71":
                format_spec.unit = UnitType.Millimeter
            elif code_s == "72":
                format_spec.unit = UnitType.Inch
            # M30 already handled above; ignore rest
            continue

        # Tool definition in body (some generators emit T<n>C<dia> here)
        if _TOOL_DEF_RE.match(line):
            _parse_tool_def(line, format_spec, apertures)
            continue

        # Tool select: bare T<n>
        m = _TOOL_SEL_RE.match(line)
        if m:
            current_tool = int(m.group(1))
            continue

        # Coordinate line
        if re.search(r"[XY]", line, re.IGNORECASE):
            current_tool = _parse_coord_line(
                line, format_spec, current_tool, apertures, nets, bbox, diagnostics, lineno
            )
            continue

        # Anything else: ignore silently (R-codes, comments without ';', etc.)

    if not format_seen:
        diagnostics.append(
            Diagnostic(
                DiagnosticSeverity.Warning,
                "No unit declaration found; defaulting to METRIC,TZ 3.3",
                None,
            )
        )

    return ParsedImage(
        draw_ops=nets,
        apertures=dict(apertures),
        layers=[layer],
        coord_states=[net_state],
        bounding_box=bbox,
        diagnostics=diagnostics,
        source_path=source_path,
    )
