from __future__ import annotations

from pathlib import Path

import pytest

from gerberdiff.parse.excellon_parser import _apply_format, _FormatSpec, parse_excellon
from gerberdiff.types import (
    ApertureState,
    ApertureType,
    DiagnosticSeverity,
    DrawOp,
    RegionFill,
    UnitType,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "gerbers-before"
_FIXTURES_ROOT = Path(__file__).parent / "fixtures"


def _op(img_draw_ops: list[DrawOp | RegionFill], idx: int = 0) -> DrawOp:
    """Return draw_ops[idx] as a DrawOp (Excellon never emits RegionFill)."""
    op = img_draw_ops[idx]
    assert isinstance(op, DrawOp)
    return op


def test_parse_minimal_excellon() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.8\n%\nT01\nX1.000Y2.000\nM30\n"
    img = parse_excellon(content)
    assert 1 in img.apertures
    assert img.apertures[1].aperture_type == ApertureType.Circle
    assert len(img.draw_ops) == 1
    assert _op(img.draw_ops).aperture_state == ApertureState.Flash


def test_excellon_coordinates_in_inches() -> None:
    # 25.4 mm -> 1.0 inch
    content = "M48\nMETRIC,LZ\nT01C25.4\n%\nT01\nX25.4Y0.0\nM30\n"
    img = parse_excellon(content)
    assert abs(_op(img.draw_ops).stop_x - 1.0) < 1e-6


def test_excellon_inch_unit_unchanged() -> None:
    content = "M48\nINCH,LZ\nT01C0.1\n%\nT01\nX1.0Y0.5\nM30\n"
    img = parse_excellon(content)
    assert abs(_op(img.draw_ops).stop_x - 1.0) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - 0.5) < 1e-6


def test_excellon_bbox_valid() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.3\n%\nT01\nX1.0Y2.0\nM30\n"
    img = parse_excellon(content)
    assert img.bounding_box.is_valid


def test_excellon_multiple_tools() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.3\nT02C0.8\n%\nT01\nX1.0Y1.0\nT02\nX2.0Y2.0\nM30\n"
    img = parse_excellon(content)
    assert 1 in img.apertures
    assert 2 in img.apertures
    assert len(img.draw_ops) == 2


def test_excellon_m30_stops_parsing() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.3\n%\nT01\nX1.0Y1.0\nM30\nX99.0Y99.0\n"
    img = parse_excellon(content)
    # Only the hit before M30 should appear
    assert len(img.draw_ops) == 1


def test_excellon_comment_lines_skipped() -> None:
    content = "M48\n;This is a comment\nMETRIC,LZ\nT01C0.5\n%\nT01\nX1.0Y1.0\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    assert not any(d.severity == DiagnosticSeverity.Error for d in img.diagnostics)


def test_excellon_no_crash_on_fixture_drill_files() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    for f in sorted(_FIXTURES.glob("*.drl")):
        img = parse_excellon(f.read_text(errors="replace"), source_path=f)
        errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
        assert errors == [], f"{f.name}: {errors}"
        assert img.bounding_box.is_valid, f"{f.name}: bounding box not valid"


# ---------------------------------------------------------------------------
# _apply_format unit tests
# ---------------------------------------------------------------------------


def _spec(unit: UnitType, zs: str, int_d: int, dec_d: int) -> _FormatSpec:
    return _FormatSpec(unit=unit, zero_suppression=zs, integer_digits=int_d, decimal_digits=dec_d)


def test_apply_format_decimal_passthrough() -> None:
    """A token with a decimal point bypasses integer-format logic."""
    spec = _spec(UnitType.Millimeter, "LZ", 3, 3)
    assert abs(_apply_format("1.234", spec)[0] - 1.234) < 1e-9
    assert abs(_apply_format("-5.678", spec)[0] - -5.678) < 1e-9


def test_apply_format_metric_lz_33() -> None:
    """METRIC,LZ 3.3: leading zeros suppressed -> left-pad then insert decimal."""
    # 5.000 mm -> file stores "5000" (leading "00" suppressed)
    spec = _spec(UnitType.Millimeter, "LZ", 3, 3)
    assert abs(_apply_format("5000", spec)[0] - 5.0) < 1e-9
    # 10.000 mm -> file stores "10000" (leading "0" suppressed)
    assert abs(_apply_format("10000", spec)[0] - 10.0) < 1e-9
    # 0.500 mm -> file stores "500" (leading "000" suppressed but none present)
    assert abs(_apply_format("500", spec)[0] - 0.5) < 1e-9


def test_apply_format_inch_tz_24() -> None:
    """INCH,TZ 2.4: trailing zeros suppressed -> right-pad then insert decimal."""
    # 1.0 inch -> full "010000" -> file stores "01" (4 trailing zeros suppressed)
    spec = _spec(UnitType.Inch, "TZ", 2, 4)
    assert abs(_apply_format("01", spec)[0] - 1.0) < 1e-9
    # 2.0 inch -> "02"
    assert abs(_apply_format("02", spec)[0] - 2.0) < 1e-9
    # 0.1234 inch -> "001234" (no trailing zeros to suppress)
    assert abs(_apply_format("001234", spec)[0] - 0.1234) < 1e-9


def test_apply_format_negative_coords() -> None:
    """Negative integer-format coordinates round-trip correctly."""
    spec = _spec(UnitType.Millimeter, "LZ", 3, 3)
    # -5.000 mm -> "-5000"
    assert abs(_apply_format("-5000", spec)[0] - -5.0) < 1e-9


def test_apply_format_zero() -> None:
    """Zero coordinates produce 0.0 under both suppression modes."""
    lz = _spec(UnitType.Millimeter, "LZ", 3, 3)
    tz = _spec(UnitType.Millimeter, "TZ", 3, 3)
    assert _apply_format("0", lz)[0] == 0.0
    assert _apply_format("0", tz)[0] == 0.0


def test_apply_format_oversized_field_truncates_and_warns() -> None:
    """An oversized coordinate field is truncated and produces a Warning diagnostic."""
    # METRIC,LZ 3.3 expects 6 digits max; supply 8 -> truncation
    content = "M48\nFMAT,2\nMETRIC,LZ\nT01C0.800\n%\nT01\nX12345678Y0\nM30\n"
    img = parse_excellon(content)
    warnings = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Warning]
    assert any("truncated" in d.message.lower() for d in warnings)


# ---------------------------------------------------------------------------
# Integer-format end-to-end tests
# ---------------------------------------------------------------------------


def test_excellon_integer_format_metric_lz_inline() -> None:
    """METRIC,LZ 3.3: integer coordinates are decoded to the correct mm values."""
    # X5000Y10000: LZ pad-left to 6: 005000 -> 005.000 mm, 010000 -> 010.000 mm
    content = "M48\nFMAT,2\nMETRIC,LZ\nT01C0.800\n%\nT01\nX5000Y10000\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    expected_x = 5.0 / 25.4
    expected_y = 10.0 / 25.4
    assert abs(_op(img.draw_ops).stop_x - expected_x) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - expected_y) < 1e-6


def test_excellon_integer_format_inch_tz_inline() -> None:
    """INCH,TZ 2.4: integer coordinates are decoded to the correct inch values."""
    # X01Y02: TZ pad-right to 6: 010000 -> 01.0000 = 1.0 inch, 020000 -> 2.0 inch
    content = "M48\nFMAT,2\nINCH,TZ\nT01C0.031\n%\nT01\nX01Y02\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    assert abs(_op(img.draw_ops).stop_x - 1.0) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - 2.0) < 1e-6


def test_excellon_integer_format_decimal_overrides_spec() -> None:
    """A decimal point in a coordinate takes precedence over the format spec."""
    content = "M48\nFMAT,2\nMETRIC,LZ\nT01C0.800\n%\nT01\nX1.234Y5.678\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    assert abs(_op(img.draw_ops).stop_x - 1.234 / 25.4) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - 5.678 / 25.4) < 1e-6


def test_excellon_integer_format_negative_coords() -> None:
    """Negative integer-format coordinates round-trip correctly end-to-end."""
    # METRIC,LZ 3.3: X-5000Y-10000 -> -005.000 mm, -010.000 mm
    content = "M48\nFMAT,2\nMETRIC,LZ\nT01C0.800\n%\nT01\nX-5000Y-10000\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    assert abs(_op(img.draw_ops).stop_x - (-5.0 / 25.4)) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - (-10.0 / 25.4)) < 1e-6


def test_excellon_explicit_digit_counts_in_header() -> None:
    """METRIC,LZ,0000.0000 overrides the 3.3 default with 4.4 digit counts."""
    # X50000 with LZ 4.4: pad-left to 8 -> 00050000 -> 0005.0000 mm = 5.0 mm
    content = "M48\nFMAT,2\nMETRIC,LZ,0000.0000\nT01C0.800\n%\nT01\nX50000Y100000\nM30\n"
    img = parse_excellon(content)
    assert len(img.draw_ops) == 1
    assert abs(_op(img.draw_ops).stop_x - 5.0 / 25.4) < 1e-6
    assert abs(_op(img.draw_ops).stop_y - 10.0 / 25.4) < 1e-6


def test_excellon_no_format_emits_warning() -> None:
    """Files without any METRIC/INCH header emit a Warning diagnostic."""
    content = "M48\nT01C0.3\n%\nT01\nX5000Y10000\nM30\n"
    img = parse_excellon(content)
    warnings = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Warning]
    assert any("unit declaration" in d.message.lower() for d in warnings)


def test_excellon_integer_format_metric_lz_fixture() -> None:
    """Fixture drill-metric-lz.drl: two tools, two hits each decoded correctly."""
    fixture = _FIXTURES_ROOT / "drill-metric-lz.drl"
    if not fixture.exists():
        pytest.skip("fixture not present")
    img = parse_excellon(fixture.read_text(), source_path=fixture)
    assert len(img.draw_ops) == 2
    assert img.bounding_box.is_valid
    # T01 hit: X5000Y10000 -> 5.0 mm, 10.0 mm -> inches
    op = _op(img.draw_ops)
    assert abs(op.stop_x - 5.0 / 25.4) < 1e-6
    assert abs(op.stop_y - 10.0 / 25.4) < 1e-6


def test_excellon_integer_format_inch_tz_fixture() -> None:
    """Fixture drill-inch-tz.drl: two tools, two hits each decoded correctly."""
    fixture = _FIXTURES_ROOT / "drill-inch-tz.drl"
    if not fixture.exists():
        pytest.skip("fixture not present")
    img = parse_excellon(fixture.read_text(), source_path=fixture)
    assert len(img.draw_ops) == 2
    assert img.bounding_box.is_valid
    # T01 hit: X01Y02 -> 1.0 inch, 2.0 inch (already in inches, no conversion)
    op = _op(img.draw_ops)
    assert abs(op.stop_x - 1.0) < 1e-6
    assert abs(op.stop_y - 2.0) < 1e-6
