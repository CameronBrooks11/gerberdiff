from __future__ import annotations

from gerberdelta.parse.gerber_parser import (
    FormatStatement,
    convert_coordinate,
    parse_aperture_definition,
    parse_format_statement,
)
from gerberdelta.types import (
    ApertureType,
    CircleAperture,
    CoordinateMode,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
    UnitType,
    ZeroOmission,
)


def test_convert_leading_zero_omission_inches() -> None:
    # FSLAX25Y25: 5 total digits, 2 integer, 3 decimal
    # (intermediate result is not asserted — only final form is)
    convert_coordinate(12500, "12500", 2, 3, ZeroOmission.Leading, UnitType.Inch)
    # raw_int=12500, dec_digits=5 → 12500/100000 = 0.125 inches
    result = convert_coordinate(12500, "12500", 2, 5, ZeroOmission.Leading, UnitType.Inch)
    assert abs(result - 0.125) < 1e-9


def test_convert_millimeter_to_inches() -> None:
    # 25.4 mm = 1 inch: raw 25400 with dec_digits=3
    result = convert_coordinate(25400, "25400", 2, 3, ZeroOmission.Leading, UnitType.Millimeter)
    assert abs(result - 1.0) < 1e-9


def test_convert_trailing_zero_omission() -> None:
    # Trailing: "125" with int=2, dec=3 → pad to 5 → "12500" → 12500 / 10^3 = 12.5
    result = convert_coordinate(125, "125", 2, 3, ZeroOmission.Trailing, UnitType.Inch)
    assert abs(result - 12.5) < 1e-9


def test_convert_trailing_negative() -> None:
    # "-125" padded to 5 digits → "-12500" → -12.5
    result = convert_coordinate(-125, "-125", 2, 3, ZeroOmission.Trailing, UnitType.Inch)
    assert abs(result - (-12.5)) < 1e-9


def test_parse_format_statement_standard() -> None:
    fs = parse_format_statement("FSLAX25Y25")
    assert fs is not None
    assert fs.zero_omission == ZeroOmission.Leading
    assert fs.coordinate_mode == CoordinateMode.Absolute
    assert fs.x_decimal == 5
    assert fs.y_decimal == 5


def test_parse_format_statement_trailing() -> None:
    fs = parse_format_statement("FSTAX26Y26")
    assert fs is not None
    assert fs.zero_omission == ZeroOmission.Trailing
    assert fs.x_integer == 2
    assert fs.x_decimal == 6


def test_parse_format_statement_no_prefix() -> None:
    # Some files omit "FS" — still parseable
    fs = parse_format_statement("LAX36Y36")
    assert fs is not None
    assert fs.x_integer == 3
    assert fs.x_decimal == 6


def test_parse_format_statement_invalid() -> None:
    assert parse_format_statement("GARBAGE") is None
    assert parse_format_statement("FSLA") is None


def test_parse_aperture_definition_circle() -> None:
    result = parse_aperture_definition("ADD10C,0.1", UnitType.Inch, {})
    assert result is not None
    d_code, ap = result
    assert d_code == 10
    assert isinstance(ap, CircleAperture)
    assert ap.aperture_type == ApertureType.Circle
    assert abs(ap.diameter - 0.1) < 1e-9
    assert ap.hole_diameter is None


def test_parse_aperture_definition_circle_with_hole() -> None:
    result = parse_aperture_definition("ADD15C,0.5X0.2", UnitType.Inch, {})
    assert result is not None
    _, ap = result
    assert isinstance(ap, CircleAperture)
    assert abs(ap.diameter - 0.5) < 1e-9
    assert ap.hole_diameter is not None
    assert abs(ap.hole_diameter - 0.2) < 1e-9


def test_parse_aperture_definition_rectangle() -> None:
    result = parse_aperture_definition("ADD11R,0.4X0.2", UnitType.Inch, {})
    assert result is not None
    _, ap = result
    assert isinstance(ap, RectangleAperture)
    assert abs(ap.width - 0.4) < 1e-9
    assert abs(ap.height - 0.2) < 1e-9


def test_parse_aperture_definition_obround() -> None:
    result = parse_aperture_definition("ADD12O,0.3X0.1", UnitType.Inch, {})
    assert result is not None
    _, ap = result
    assert isinstance(ap, ObroundAperture)
    assert abs(ap.width - 0.3) < 1e-9


def test_parse_aperture_definition_polygon() -> None:
    result = parse_aperture_definition("ADD13P,0.5X6X45", UnitType.Inch, {})
    assert result is not None
    _, ap = result
    assert isinstance(ap, PolygonAperture)
    assert abs(ap.outer_diameter - 0.5) < 1e-9
    assert ap.num_vertices == 6
    assert abs(ap.rotation - 45.0) < 1e-9


def test_parse_aperture_definition_mm_unit_scale() -> None:
    # 25.4 mm diameter should become 1.0 inch
    result = parse_aperture_definition("ADD10C,25.4", UnitType.Millimeter, {})
    assert result is not None
    _, ap = result
    assert isinstance(ap, CircleAperture)
    assert abs(ap.diameter - 1.0) < 1e-9


def test_parse_aperture_definition_dcode_too_small() -> None:
    # D codes 1-9 are reserved
    assert parse_aperture_definition("ADD09C,0.1", UnitType.Inch, {}) is None


def test_parse_aperture_definition_unknown_macro() -> None:
    # Macro name not in macro_map → None
    assert parse_aperture_definition("ADD10MYMACRO,1.0", UnitType.Inch, {}) is None


def test_format_statement_is_dataclass() -> None:
    fs = FormatStatement(
        zero_omission=ZeroOmission.Leading,
        coordinate_mode=CoordinateMode.Absolute,
        x_integer=2,
        x_decimal=5,
        y_integer=2,
        y_decimal=5,
    )
    assert fs.x_integer == 2
    assert fs.y_decimal == 5
