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


# ---------------------------------------------------------------------------
# P4-1: Block aperture does not leak drawing state
# ---------------------------------------------------------------------------


def test_block_aperture_does_not_leak_aperture_state() -> None:
    # D01 (draw) inside the block must not change aperture_state for the parent.
    # After %AB*%, a D03 flash at (0,0) should emit exactly one Flash net.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10C,0.1*%"
        "%ADD11C,0.1*%"
        "%ABD12*%"
        "D10*X0Y0D01*"  # draw inside block (aperture_state=On inside block)
        "%AB*%"
        "D11*X0Y0D03*"  # flash in parent -- aperture_state must be Flash, not On
        "M02*"
    )
    img = parse_gerber(gerber)
    from gerberdelta.types import ApertureState, DrawOp
    flashes = [op for op in img.draw_ops if isinstance(op, DrawOp) and op.aperture_state == ApertureState.Flash]
    assert len(flashes) == 1


def test_block_aperture_does_not_leak_interpolation_mode() -> None:
    # G02 (CW arc mode) inside block must not affect parent interpolation.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10C,0.1*%"
        "%ABD11*%"
        "G02*"  # CW arc mode inside block
        "%AB*%"
        "D10*X10000Y0D01*"  # linear draw in parent
        "M02*"
    )
    img = parse_gerber(gerber)
    from gerberdelta.types import DrawOp, InterpolationMode
    linear_ops = [
        op for op in img.draw_ops
        if isinstance(op, DrawOp) and op.interpolation == InterpolationMode.Linear
    ]
    assert len(linear_ops) >= 1


def test_block_aperture_does_not_leak_macro_definition() -> None:
    # A macro defined inside the block must not appear in the parent macro map.
    # We verify indirectly: an AD referencing the macro in the parent produces an
    # Error diagnostic (macro not found), not a successful aperture.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ABD10*%"
        "%AMINNERCIRC*1,0.1,0,0,0*%"  # macro defined inside block
        "%AB*%"
        "%ADD11INNERCIRC,0.1*%"  # reference in parent -- should be Error
        "M02*"
    )
    img = parse_gerber(gerber)
    errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
    assert any("INNERCIRC" in d.message for d in errors)


def test_block_aperture_does_not_leak_unit_change() -> None:
    # %MOMM% inside the block must not change the parent unit.
    # In parent (inch), a coordinate of X100000 with FSLAX25Y25 = 1.0 inch.
    # If unit leaked as mm, it would be / 25.4 ≈ 0.0394 inch.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10C,0.001*%"
        "%ABD11*%"
        "%MOMM*%"  # switch to mm inside block
        "%AB*%"
        "D10*X100000Y0D03*"  # flash; with inch unit -> 1.0 inch
        "M02*"
    )
    img = parse_gerber(gerber)
    from gerberdelta.types import DrawOp
    ops = [op for op in img.draw_ops if isinstance(op, DrawOp)]
    assert ops, "expected at least one DrawOp"
    assert abs(ops[-1].stop_x - 1.0) < 1e-4, f"unit leaked: stop_x={ops[-1].stop_x}"


# ---------------------------------------------------------------------------
# P4-2: Arc bounding box extends beyond chord endpoints
# ---------------------------------------------------------------------------


def test_arc_net_expands_bounding_box_beyond_chord() -> None:
    # 180-degree CCW arc from (1,0) to (-1,0) centred at origin.
    # The top of the arc is at y=1; the chord midpoint is at y=0.
    # The bounding box must include y≈1.0 (the arc peak).
    # G75 multi-quadrant, G03 CCW, aperture radius 0.
    # I=-1, J=0 means centre = start + (I,J) = (1,0)+(-1,0) = (0,0). Correct.
    # FSLAX25Y25 with MOIN: 1 inch = 100000 units.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10C,0.001*%"
        "D10*"
        "G75*G03*"
        "X100000Y0D02*"         # move to start (1,0)
        "X-100000Y0I-100000J0D01*"  # 180° CCW arc to (-1,0)
        "M02*"
    )
    img = parse_gerber(gerber)
    assert img.bounding_box.is_valid
    assert img.bounding_box.max_y > 0.9, (
        f"arc bbox max_y={img.bounding_box.max_y:.4f} should be ~1.0 for 180° arc"
    )


# ---------------------------------------------------------------------------
# P4-3: Step-and-repeat bounding box covers all instances
# ---------------------------------------------------------------------------


def test_sr_bounding_box_covers_all_instances() -> None:
    # SRX3Y1I1.0J0.0: 3 instances spaced 1 inch apart along X.
    # A flash at (0,0) with 3 instances → last instance at (2,0).
    # BBox must extend to at least x≈2.0.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10C,0.001*%"
        "%SRX3Y1I100000J0*%"
        "D10*X0Y0D03*"
        "%SR*%"
        "M02*"
    )
    img = parse_gerber(gerber)
    assert img.bounding_box.is_valid
    assert img.bounding_box.max_x >= 1.9, (
        f"SR bbox max_x={img.bounding_box.max_x:.4f} should cover all 3 instances (~2.0)"
    )


# ---------------------------------------------------------------------------
# P4-4: Step-and-repeat close preserves polarity
# ---------------------------------------------------------------------------


def test_sr_close_preserves_polarity() -> None:
    # Set clear polarity, open SR, close SR.  Layer after close must be Clear.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%LPC*%"                    # clear polarity
        "%SRX2Y1I100000J0*%"
        "%ADD10C,0.001*%"
        "D10*X0Y0D03*"
        "%SR*%"                     # close SR
        "M02*"
    )
    img = parse_gerber(gerber)
    last_layer = img.layers[-1]
    assert last_layer.polarity == Polarity.Clear, (
        f"SR close reset polarity to {last_layer.polarity}, expected Clear"
    )


# ---------------------------------------------------------------------------
# P4-6: Unknown macro aperture emits Error; malformed emits Warning
# ---------------------------------------------------------------------------


def test_aperture_forward_reference_unknown_macro_emits_error() -> None:
    # Reference a macro that was never defined → Error severity.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADD10NOTDEFINED,1.0*%"
        "M02*"
    )
    img = parse_gerber(gerber)
    errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
    assert any("NOTDEFINED" in d.message for d in errors), (
        f"expected Error about NOTDEFINED, got: {img.diagnostics}"
    )


def test_aperture_malformed_definition_emits_warning_not_error() -> None:
    # A definition that can't be parsed at all (no D-code) → Warning, not Error.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%ADGARBAGE*%"
        "M02*"
    )
    img = parse_gerber(gerber)
    errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
    warnings = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Warning]
    assert errors == [], f"unexpected errors: {errors}"
    assert any("aperture" in d.message.lower() for d in warnings)


# ---------------------------------------------------------------------------
# P7-1: Incremental coordinate mode
# ---------------------------------------------------------------------------


def test_incremental_mode_accumulates_coordinates() -> None:
    """G91 switches to incremental mode; each coordinate adds to the previous."""
    # Two successive D01 moves of 0.1 inch (10000 units at X2.5Y2.5 format).
    # In incremental mode the second move's stop position should be 0.2 inch.
    gerber = (
        "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%"
        "D10*"
        "G01*G91*"          # linear, incremental
        "X10000Y00000D01*"  # move +0.1 inch from (0,0) → stop at (0.1, 0.0)
        "X10000Y00000D01*"  # move +0.1 inch from (0.1,0) → stop at (0.2, 0.0)
        "M02*"
    )
    img = parse_gerber(gerber)
    from gerberdelta.types import DrawOp
    ops = [op for op in img.draw_ops if isinstance(op, DrawOp)]
    assert len(ops) >= 2, f"expected at least 2 DrawOps, got {len(ops)}"
    # Second net must end further right than the first
    assert ops[1].stop_x > ops[0].stop_x, (
        f"incremental: second stop_x ({ops[1].stop_x}) should exceed first ({ops[0].stop_x})"
    )
    assert abs(ops[1].stop_x - 0.2) < 1e-6, (
        f"expected stop_x≈0.2 inch, got {ops[1].stop_x}"
    )


def test_incremental_mode_returns_to_absolute_on_G90() -> None:
    """After G90, coordinates are absolute again (not accumulated)."""
    gerber = (
        "%FSLAX25Y25*%%MOIN*%%ADD10C,0.001*%"
        "D10*"
        "G91*"              # incremental
        "X10000Y00000D01*"  # incremental move +0.1 → stop at (0.1, 0)
        "G90*"              # back to absolute
        "X10000Y00000D01*"  # absolute move to (0.1, 0) → stop_x = 0.1 (not 0.2)
        "M02*"
    )
    img = parse_gerber(gerber)
    from gerberdelta.types import DrawOp
    ops = [op for op in img.draw_ops if isinstance(op, DrawOp)]
    assert len(ops) >= 2
    # After G90, the second move is absolute: stop at exactly X=0.1 (same as first)
    assert abs(ops[1].stop_x - 0.1) < 1e-6, (
        f"after G90 expected stop_x≈0.1 (absolute), got {ops[1].stop_x}"
    )


# ---------------------------------------------------------------------------
# P7-2: Step-and-repeat parsing
# ---------------------------------------------------------------------------


def test_sr_parse_records_step_and_repeat_on_layer() -> None:
    """%%SRX3Y2I1.0J0.5*%% sets step-and-repeat on the current layer."""
    gerber = (
        "%FSLAX25Y25*%%MOIN*%"
        "%SRX3Y2I1.0J0.5*%"
        "%ADD10C,0.001*%"
        "X0Y0D03*"
        "%SR*%"
        "M02*"
    )
    img = parse_gerber(gerber)
    # The SR block produces a layer; find one with x>1.
    sr_layers = [la for la in img.layers if la.step_and_repeat.x > 1]
    assert len(sr_layers) >= 1, "expected at least one layer with SR x>1"
    sr = sr_layers[0].step_and_repeat
    assert sr.x == 3
    assert sr.y == 2
    assert abs(sr.dist_x - 1.0) < 1e-9
    assert abs(sr.dist_y - 0.5) < 1e-9
