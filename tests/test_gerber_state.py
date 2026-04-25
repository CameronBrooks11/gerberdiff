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
    # G36/G37 should produce a single RegionFill object, not sentinel DrawOps
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%G36*X10000Y10000D01*X20000D01*G37*M02*"
    img = parse_gerber(content)
    from gerberdelta.types import DrawOp, RegionFill

    region_fills = [op for op in img.draw_ops if isinstance(op, RegionFill)]
    assert len(region_fills) == 1, "expected exactly one RegionFill in draw_ops"
    rf = region_fills[0]
    assert len(rf.segments) == 2, "expected two interior segment DrawOps"
    assert all(isinstance(s, DrawOp) for s in rf.segments)
    # no plain DrawOp should be the old sentinel (enum members no longer exist)
    plain_ops = [op for op in img.draw_ops if isinstance(op, DrawOp)]
    assert len(plain_ops) == 0, "expected no DrawOps outside the RegionFill"


def test_region_fill_bounding_box_expanded() -> None:
    # Interior segment coordinates must expand the image bounding box
    content = (
        "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%"
        "G36*D02*X0Y0D01*X100000Y100000D01*G37*M02*"
    )
    img = parse_gerber(content)
    bb = img.bounding_box
    assert bb.is_valid
    assert bb.max_x > 0.0
    assert bb.max_y > 0.0


def test_region_fill_unclosed_at_eof_warns() -> None:
    # G36 without G37 before M02 should emit a Warning diagnostic
    content = "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%G36*X10000Y10000D01*M02*"
    img = parse_gerber(content)
    warnings = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Warning]
    assert any("region" in d.message.lower() for d in warnings)


def test_region_fill_renders_pixel() -> None:
    # End-to-end: a filled square region must produce at least one opaque pixel
    content = (
        "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%"
        "G36*"
        "X0Y0D02*"
        "X100000Y0D01*"
        "X100000Y100000D01*"
        "X0Y100000D01*"
        "X0Y0D01*"
        "G37*"
        "M02*"
    )
    from gerberdelta.parse.gerber_state import parse_gerber as _pg
    from gerberdelta.render.renderer import render_to_numpy
    from gerberdelta.render.viewport import compute_viewport

    img = _pg(content)
    vp = compute_viewport(img.bounding_box, width=64, height=64)
    arr = render_to_numpy(img, vp)
    # alpha channel > 0 means at least one drawn pixel
    assert arr[..., 3].max() > 0


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
