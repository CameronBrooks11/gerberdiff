"""Edge-case tests for the geometry engine's guard paths.

Covers degenerate inputs, limits, and fallbacks that the mainline tests do
not reach: block nesting depth, invalid layer indices, zero-dimension
apertures, degenerate regions, diagnostic forwarding, and the
equal-geometry attribution guard.
"""

from __future__ import annotations

import math
from pathlib import Path

from gerberdiff.geometry import compute_geometry_diff
from gerberdiff.geometry.attribute import attribute_changes, partition_unchanged
from gerberdiff.geometry.expand import flash_geometry, stroke_geometry
from gerberdiff.geometry.layer_geometry import LayerGeometry, build_layer_geometry
from gerberdiff.parse.gerber_state import parse_gerber
from gerberdiff.types import (
    ApertureState,
    ArcSegment,
    BlockAperture,
    CircleAperture,
    Diagnostic,
    DiagnosticSeverity,
    DrawOp,
    InterpolationMode,
    MacroAperture,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
)

_HEADER = "%FSLAX26Y26*%\n%MOIN*%\n"
_FOOTER = "M02*\n"

_MOVE_TOL = 0.005 / 25.4
_GATE = 0.2 / 25.4
_AREA_TOL = 0.01


def _gerber(*body_lines: str) -> str:
    return _HEADER + "\n".join(body_lines) + "\n" + _FOOTER


def _build(*body_lines: str) -> LayerGeometry:
    return build_layer_geometry(parse_gerber(_gerber(*body_lines)))


def _op(
    *,
    start: tuple[float, float] = (0.0, 0.0),
    stop: tuple[float, float] = (0.0, 0.0),
    state: ApertureState = ApertureState.On,
    arc: ArcSegment | None = None,
) -> DrawOp:
    return DrawOp(
        start_x=start[0],
        start_y=start[1],
        stop_x=stop[0],
        stop_y=stop[1],
        aperture_index=10,
        aperture_state=state,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
        arc_segment=arc,
    )


# ---------------------------------------------------------------------------
# Block nesting depth limit
# ---------------------------------------------------------------------------


def test_block_nesting_beyond_depth_limit_skipped() -> None:
    """Blocks nested past the depth limit contribute no geometry.

    Builds a chain of 12 nested block apertures programmatically (the
    parser itself caps nesting, so construct the IR directly).
    """
    from gerberdiff.types import LayerState, ParsedImage

    innermost = BlockAperture(
        draw_ops=[_op(stop=(0.0, 0.0), state=ApertureState.Flash)],
        apertures={10: CircleAperture(diameter=0.1)},
        layers=[LayerState()],
    )
    block = innermost
    for _ in range(12):
        block = BlockAperture(
            draw_ops=[
                DrawOp(
                    start_x=0.0,
                    start_y=0.0,
                    stop_x=0.0,
                    stop_y=0.0,
                    aperture_index=20,
                    aperture_state=ApertureState.Flash,
                    interpolation=InterpolationMode.Linear,
                    layer_index=0,
                    net_state_index=0,
                )
            ],
            apertures={20: block},
            layers=[LayerState()],
        )

    parsed = ParsedImage(
        draw_ops=[
            DrawOp(
                start_x=0.0,
                start_y=0.0,
                stop_x=0.0,
                stop_y=0.0,
                aperture_index=20,
                aperture_state=ApertureState.Flash,
                interpolation=InterpolationMode.Linear,
                layer_index=0,
                net_state_index=0,
            )
        ],
        apertures={20: block},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=parse_gerber(_gerber("%ADD10C,0.1*%", "D10*", "X0Y0D03*")).bounding_box,
        diagnostics=[],
    )
    lg = build_layer_geometry(parsed)
    assert lg.ops == []  # the flash is >10 levels deep: skipped


def test_invalid_layer_index_skipped() -> None:
    """Ops referencing a layer index out of range are dropped."""
    from gerberdiff.types import LayerState, ParsedImage

    parsed = ParsedImage(
        draw_ops=[
            DrawOp(
                start_x=0.0,
                start_y=0.0,
                stop_x=0.0,
                stop_y=0.0,
                aperture_index=10,
                aperture_state=ApertureState.Flash,
                interpolation=InterpolationMode.Linear,
                layer_index=99,  # no such layer
                net_state_index=0,
            )
        ],
        apertures={10: CircleAperture(diameter=0.1)},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=parse_gerber(_gerber("%ADD10C,0.1*%", "D10*", "X0Y0D03*")).bounding_box,
        diagnostics=[],
    )
    lg = build_layer_geometry(parsed)
    assert lg.ops == []


# ---------------------------------------------------------------------------
# Degenerate apertures at the layer level
# ---------------------------------------------------------------------------


def test_zero_dimension_apertures_emit_no_ops() -> None:
    src = _gerber(
        "%ADD10C,0*%",  # zero-diameter circle
        "%ADD11R,0X0.1*%",  # zero-width rect
        "%ADD12P,0X4*%",  # zero-diameter polygon
        "D10*",
        "X0Y0D03*",
        "D11*",
        "X0Y0D03*",
        "D12*",
        "X0Y0D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.ops == []


def test_macro_flash_eagerly_expanded_at_layer_level() -> None:
    """Macro flashes expand eagerly; geometry is shared via the thunk."""
    src = _gerber(
        "%AMDONUT*1,1,0.1,0,0*1,0,0.05,0,0*%",
        "%ADD10DONUT*%",
        "D10*",
        "X0Y0D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert len(lg.ops) == 1
    expected = math.pi * (0.05**2 - 0.025**2)
    assert math.isclose(lg.ops[0].area, expected, rel_tol=5e-3)


def test_stroke_with_block_aperture_skipped() -> None:
    """D01 with a block aperture is not meaningful; no op emitted."""
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X0Y0D03*",
        "%AB*%",
        "D10*",
        "X0Y0D02*",
        "X100000Y0D01*",  # stroke with the block aperture
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.ops == []


def test_nonround_arc_stroke_info_diagnostic_at_layer_level() -> None:
    """The round-brush approximation Info surfaces from the build, without
    expanding any geometry."""
    src = _gerber(
        "%ADD10R,0.04X0.02*%",
        "G75*",
        "D10*",
        "X50000Y0D02*",
        "G03*",
        "X0Y50000I-50000J0D01*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    infos = [d for d in lg.diagnostics if d.severity == DiagnosticSeverity.Info]
    assert any("approximated" in d.message for d in infos)
    assert len(lg.ops) == 1


def test_degenerate_region_skipped_at_layer_level() -> None:
    """A region with fewer than two drawable segments emits no op."""
    src = _gerber(
        "G36*",
        "X0Y0D02*",
        "X100000Y0D01*",  # single segment: no enclosable contour
        "G37*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.ops == []


def test_region_with_arc_has_conservative_bounds() -> None:
    """Region bounds include arc extents (analytic, pre-expansion)."""
    src = _gerber(
        "G75*",
        "G36*",
        "X100000Y0D02*",
        "G03*",
        "X-100000Y0I-100000J0D01*",  # ccw half circle over the top
        "G01*",
        "X100000Y0D01*",
        "G37*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert len(lg.ops) == 1
    _min_x, _min_y, _max_x, max_y = lg.ops[0].bounds
    assert max_y >= 0.099  # arc apex near y=0.1 must be inside the bbox
    assert math.isclose(lg.ops[0].area, math.pi * 0.1**2 / 2.0, rel_tol=5e-3)


def test_empty_geometry_centroid_falls_back_to_bbox_centre() -> None:
    """A region whose contour is collinear has bounds but empty geometry;
    centroid access must not crash (bbox-centre fallback)."""
    from gerberdiff.types import LayerState, ParsedImage, RegionFill

    region = RegionFill(
        layer_index=0,
        net_state_index=0,
        segments=[
            _op(stop=(0.0, 0.0), state=ApertureState.Off),
            _op(start=(0.0, 0.0), stop=(1.0, 0.0), state=ApertureState.On),
            _op(start=(1.0, 0.0), stop=(2.0, 0.0), state=ApertureState.On),
        ],
    )
    parsed = ParsedImage(
        draw_ops=[region],
        apertures={},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=parse_gerber(_gerber("%ADD10C,0.1*%", "D10*", "X0Y0D03*")).bounding_box,
        diagnostics=[],
    )
    lg = build_layer_geometry(parsed)
    assert len(lg.ops) == 1
    op = lg.ops[0]
    assert op.geom.is_empty
    assert math.isclose(op.centroid_x, 1.0, abs_tol=1e-9)  # bbox centre
    assert math.isclose(op.centroid_y, 0.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Degenerate strokes at the expand level
# ---------------------------------------------------------------------------


def test_zero_diameter_circle_stroke_empty() -> None:
    geom, _ = stroke_geometry(_op(stop=(1.0, 0.0)), CircleAperture(diameter=0.0))
    assert geom.is_empty


def test_zero_dims_rect_stroke_empty() -> None:
    geom, _ = stroke_geometry(_op(stop=(1.0, 0.0)), RectangleAperture(width=0.0, height=0.1))
    assert geom.is_empty


def test_zero_diameter_circle_arc_stroke_empty() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=0.0, end_angle_deg=90.0
    )
    geom, _ = stroke_geometry(_op(stop=(0.0, 0.5), arc=arc), CircleAperture(diameter=0.0))
    assert geom.is_empty


def test_polygon_arc_stroke_uses_outer_diameter_brush() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=0.0, end_angle_deg=90.0
    )
    op = _op(start=(0.5, 0.0), stop=(0.0, 0.5), arc=arc)
    geom, diags = stroke_geometry(op, PolygonAperture(outer_diameter=0.04, num_vertices=6))
    assert not geom.is_empty
    assert len(diags) == 1


def test_degenerate_obround_arc_stroke_empty() -> None:
    arc = ArcSegment(
        center_x=0.0, center_y=0.0, radius=0.5, start_angle_deg=0.0, end_angle_deg=90.0
    )
    geom, _ = stroke_geometry(_op(stop=(0.0, 0.5), arc=arc), ObroundAperture(width=0.0, height=0.0))
    assert geom.is_empty


def test_flash_geometry_dispatches_macro() -> None:
    """flash_geometry routes MacroAperture through the macro expander."""
    from gerberdiff.parse.macro_parser import parse_macro_body

    ap = MacroAperture(macro_def=parse_macro_body("M", "1,1,0.1,0,0,0"), params=[])
    geom, diags = flash_geometry(_op(stop=(1.0, 1.0), state=ApertureState.Flash), ap)
    assert not diags
    assert math.isclose(geom.centroid.x, 1.0, abs_tol=1e-9)
    assert math.isclose(geom.area, math.pi * 0.05**2, rel_tol=5e-3)


# ---------------------------------------------------------------------------
# Attribution: equal-geometry guard
# ---------------------------------------------------------------------------


def test_equal_geometry_different_aperture_is_unchanged() -> None:
    """A square obround re-declared as a circle of the same diameter has
    different signatures but identical geometry: not a change."""
    a = _build("%ADD10O,0.1X0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    parts = partition_unchanged(a.ops, b.ops)
    assert parts.a_only and parts.b_only  # signatures differ...
    changes, unchanged = attribute_changes(
        parts, move_tol=_MOVE_TOL, gate_radius=_GATE, area_tol=_AREA_TOL
    )
    assert changes == []  # ...but the geometry is identical
    assert unchanged == 1


# ---------------------------------------------------------------------------
# Driver diagnostic forwarding
# ---------------------------------------------------------------------------


def test_driver_forwards_parse_and_expansion_diagnostics(tmp_path: Path) -> None:
    before = tmp_path / "b"
    after = tmp_path / "a"
    before.mkdir()
    after.mkdir()
    # Non-round arc stroke -> expansion Info; no FS statement -> parse Info.
    src = (
        "%MOIN*%\n%ADD10R,0.04X0.02*%\nG75*\nD10*\n"
        "X50000Y0D02*\nG03*\nX0Y50000I-50000J0D01*\n" + _FOOTER
    )
    (before / "x-F.Cu.gbr").write_text(src)
    (after / "x-F.Cu.gbr").write_text(src)

    seen: list[tuple[str, Diagnostic]] = []
    compute_geometry_diff(
        before, after, on_diagnostic=lambda path, diag: seen.append((path.name, diag))
    )
    messages = [d.message for _, d in seen]
    assert any("approximated" in m for m in messages)  # expansion diagnostic
    assert all(name == "x-F.Cu.gbr" for name, _ in seen)
