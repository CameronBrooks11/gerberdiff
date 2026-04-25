from __future__ import annotations

from pathlib import Path

import pytest

from gerberdelta.parse.gerber_state import parse_gerber
from gerberdelta.types import ApertureType, DiagnosticSeverity, Polarity

_FIXTURES = Path(__file__).parent / "fixtures" / "gerbers-before"


def test_parse_minimal() -> None:
    # FSLAX25Y25, MOMM unit, circle D10, linear draw, end
    content = "%FSLAX25Y25*%%MOMM*%%ADD10C,1.0*%G01*X100000Y100000D01*M02*"
    img = parse_gerber(content)
    assert img.bounding_box.is_valid
    assert len(img.draw_ops) > 0
    assert not any(d.severity == DiagnosticSeverity.Error for d in img.diagnostics)


def test_parse_circle_aperture() -> None:
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.01*%X10000Y10000D03*M02*"
    img = parse_gerber(content)
    assert 10 in img.apertures
    assert img.apertures[10].aperture_type == ApertureType.Circle


def test_clear_polarity_creates_new_layer() -> None:
    content = "%FSLAX25Y25*%%MOIN*%%LPC*%M02*"
    img = parse_gerber(content)
    assert len(img.layers) == 2
    assert img.layers[1].polarity == Polarity.Clear


def test_bounding_box_positive_coords() -> None:
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%X10000Y20000D03*M02*"
    img = parse_gerber(content)
    assert img.bounding_box.min_x > 0
    assert img.bounding_box.min_y > 0


def test_bounding_box_negative_coords() -> None:
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%X-10000Y-20000D03*M02*"
    img = parse_gerber(content)
    assert img.bounding_box.min_x < 0
    assert img.bounding_box.min_y < 0


def test_no_format_statement_adds_info_diagnostic() -> None:
    # A minimal file with no FS should get an Info diagnostic about the default
    content = "M02*"
    img = parse_gerber(content)
    assert any(d.severity == DiagnosticSeverity.Info for d in img.diagnostics)


def test_region_fill_markers_in_net_list() -> None:
    # G36/G37 should produce RegionStart/RegionEnd sentinel nets
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%G36*X10000Y10000D01*X20000D01*G37*M02*"
    img = parse_gerber(content)
    from gerberdelta.types import InterpolationMode

    modes = [n.interpolation for n in img.draw_ops]
    assert InterpolationMode.RegionStart in modes
    assert InterpolationMode.RegionEnd in modes


def test_aperture_select_does_not_emit_net() -> None:
    # D10 (aperture select) alone should NOT produce a drawing net
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%D10*M02*"
    img = parse_gerber(content)
    assert len(img.draw_ops) == 0


def test_multiple_apertures_defined() -> None:
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.01*%%ADD11R,0.02X0.03*%%ADD12O,0.04X0.02*%M02*"
    img = parse_gerber(content)
    assert 10 in img.apertures
    assert 11 in img.apertures
    assert 12 in img.apertures
    assert img.apertures[10].aperture_type == ApertureType.Circle
    assert img.apertures[11].aperture_type == ApertureType.Rectangle
    assert img.apertures[12].aperture_type == ApertureType.Obround


def test_linear_draw_sequence() -> None:
    # Three successive D01 blocks should produce three nets
    content = "%FSLAX25Y25*%%MOIN*%D10*X0Y0D02*X10000Y0D01*X10000Y10000D01*X0Y10000D01*M02*"
    img = parse_gerber(content)
    # D02 (move) + 3x D01 (draw) = 4 nets total
    assert len(img.draw_ops) == 4


def test_source_path_stored() -> None:
    p = Path("fake/test.gbr")
    img = parse_gerber("M02*", source_path=p)
    assert img.source_path == p


def test_no_crash_on_fixture_files() -> None:
    """Parse every gerbers-before fixture without raising or producing errors."""
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    for f in sorted(_FIXTURES.glob("*")):
        img = parse_gerber(f.read_text(errors="replace"), source_path=f)
        assert img is not None
        errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
        assert errors == [], f"{f.name}: {errors}"


def test_malformed_macro_records_error_diagnostic() -> None:
    """A macro with a non-integer variable index produces a DiagnosticSeverity.Error."""
    gerber = "%AMbadmacro*$notanint=1*%\nM02*\n"
    img = parse_gerber(gerber)
    errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
    assert len(errors) == 1
    assert "badmacro" in errors[0].message
