from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from gerberdelta.types import (
    CircleAperture,
    CoordinateMode,
    MacroAperture,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
    UnitType,
    ZeroOmission,
)

if TYPE_CHECKING:
    from gerberdelta.parse.macro_parser import MacroDef  # type: ignore[import-untyped]


@dataclass
class FormatStatement:
    """Parsed result of a Gerber FS (format statement) extended command."""

    zero_omission: ZeroOmission
    coordinate_mode: CoordinateMode
    x_integer: int   # number of integer digits for X coordinates
    x_decimal: int   # number of decimal digits for X coordinates
    y_integer: int
    y_decimal: int


def convert_coordinate(
    raw_int: int,
    raw_str: str,
    int_digits: int,
    dec_digits: int,
    zero_omission: ZeroOmission,
    unit: UnitType,
) -> float:
    """Convert a raw integer coordinate value to inches.

    Leading zero omission (default, most common):
        Divide raw_int directly by 10^dec_digits.

    Trailing zero omission:
        The digit string has trailing zeros omitted.  Pad (excluding sign) to
        int_digits+dec_digits with '0' on the right, then divide by 10^dec_digits.

    Always: if unit == Millimeter, divide result by 25.4 to convert to inches.
    """
    value: float
    if zero_omission == ZeroOmission.Trailing:
        total_digits = int_digits + dec_digits
        negative = raw_str.startswith("-")
        digits = raw_str.lstrip("+-")
        padded = digits.ljust(total_digits, "0")
        value = int(padded) / (10**dec_digits)
        if negative:
            value = -value
    else:
        # Leading or Explicit: raw_int is already the full integer representation
        value = raw_int / (10**dec_digits)

    if unit == UnitType.Millimeter:
        value /= 25.4
    return value


def parse_format_statement(s: str) -> FormatStatement | None:
    """Parse a FS... extended command string (without the % delimiters).

    Expected form: FSLAXnnYnn
      - Optional FS prefix
      - Zero omission: L (leading, most common) | T (trailing) | D (explicit)
      - Coordinate mode: A (absolute) | I (incremental)
      - Xij: i = integer digits, j = decimal digits
      - Yij: same for Y axis

    Returns None if the string cannot be parsed.
    """
    # Strip optional "FS" prefix
    body = s[2:] if s.startswith("FS") else s
    idx = 0

    # Zero omission
    zero_omission: ZeroOmission
    if idx < len(body) and body[idx] == "L":
        zero_omission = ZeroOmission.Leading
        idx += 1
    elif idx < len(body) and body[idx] == "T":
        zero_omission = ZeroOmission.Trailing
        idx += 1
    elif idx < len(body) and body[idx] == "D":
        zero_omission = ZeroOmission.Explicit
        idx += 1
    else:
        zero_omission = ZeroOmission.Leading  # default per RS-274X spec

    # Coordinate mode
    coord_mode: CoordinateMode
    if idx < len(body) and body[idx] == "A":
        coord_mode = CoordinateMode.Absolute
        idx += 1
    elif idx < len(body) and body[idx] == "I":
        coord_mode = CoordinateMode.Incremental
        idx += 1
    else:
        coord_mode = CoordinateMode.Absolute

    # X digits — expect 'X' followed by two digit characters
    if idx >= len(body) or body[idx] != "X":
        return None
    idx += 1
    if idx + 1 >= len(body):
        return None
    x_int = int(body[idx], 10)
    idx += 1
    x_dec = int(body[idx], 10)
    idx += 1
    if not (0 <= x_int <= 9 and 0 <= x_dec <= 9):
        return None

    # Y digits — expect 'Y' followed by two digit characters
    if idx >= len(body) or body[idx] != "Y":
        return None
    idx += 1
    if idx + 1 >= len(body):
        return None
    y_int = int(body[idx], 10)
    idx += 1
    y_dec = int(body[idx], 10)
    if not (0 <= y_int <= 9 and 0 <= y_dec <= 9):
        return None

    return FormatStatement(
        zero_omission=zero_omission,
        coordinate_mode=coord_mode,
        x_integer=x_int,
        x_decimal=x_dec,
        y_integer=y_int,
        y_decimal=y_dec,
    )


def parse_aperture_definition(
    s: str,
    unit: UnitType,
    macro_map: dict[str, MacroDef],
) -> tuple[int, CircleAperture | RectangleAperture | ObroundAperture | PolygonAperture | MacroAperture] | None:
    """Parse an AD... extended command string (without the % delimiters).

    Returns (d_code, aperture) or None if unparseable.
    d_code must be >= 10 (codes 1-9 are reserved per RS-274X spec).

    Standard aperture types: C (Circle), R (Rectangle), O (Obround), P (Polygon).
    Parameters are separated by X.  Hole diameter is the last optional parameter.

    Unit scale: parameters in mm files are divided by 25.4; all output is in inches.

    Macro apertures: look up name in macro_map; store raw params (NOT scaled) and
    unit_scale on the aperture — the renderer applies scaling at draw time.
    """
    # Strip optional "AD" prefix
    body = s[2:] if s.startswith("AD") else s

    if not body or body[0] != "D":
        return None

    # Read d_code digits (must be ≥ 10)
    i = 1
    while i < len(body) and body[i].isdigit():
        i += 1
    d_code_str = body[1:i]
    if not d_code_str:
        return None
    d_code = int(d_code_str)
    if d_code < 10:
        return None

    # Split remainder into aperture-type name and parameter string
    remainder = body[i:]
    comma_pos = remainder.find(",")
    if comma_pos == -1:
        aperture_name = remainder
        params_str = ""
    else:
        aperture_name = remainder[:comma_pos]
        params_str = remainder[comma_pos + 1 :]

    params = [float(p) for p in params_str.split("X")] if params_str else []

    # Unit scale factor: mm → inch
    unit_scale = 1.0 / 25.4 if unit == UnitType.Millimeter else 1.0

    if aperture_name == "C":
        return d_code, CircleAperture(
            diameter=(params[0] if params else 0.0) * unit_scale,
            hole_diameter=params[1] * unit_scale if len(params) > 1 else None,
        )

    if aperture_name == "R":
        return d_code, RectangleAperture(
            width=(params[0] if params else 0.0) * unit_scale,
            height=(params[1] if len(params) > 1 else 0.0) * unit_scale,
            hole_diameter=params[2] * unit_scale if len(params) > 2 else None,
        )

    if aperture_name == "O":
        return d_code, ObroundAperture(
            width=(params[0] if params else 0.0) * unit_scale,
            height=(params[1] if len(params) > 1 else 0.0) * unit_scale,
            hole_diameter=params[2] * unit_scale if len(params) > 2 else None,
        )

    if aperture_name == "P":
        return d_code, PolygonAperture(
            outer_diameter=(params[0] if params else 0.0) * unit_scale,
            num_vertices=int(params[1]) if len(params) > 1 else 4,
            rotation=params[2] if len(params) > 2 else 0.0,
            hole_diameter=params[3] * unit_scale if len(params) > 3 else None,
        )

    # Macro aperture — look up definition by name
    macro_def = macro_map.get(aperture_name)
    if macro_def is None:
        return None
    return d_code, MacroAperture(
        macro_def=macro_def,
        params=params,
        unit_scale=unit_scale,
    )
