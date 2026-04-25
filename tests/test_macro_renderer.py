from __future__ import annotations

import cairocffi as cairo
import numpy as np

from gerberdiff.parse.macro_parser import parse_macro_body
from gerberdiff.render.macro_renderer import compute_macro_bounding_radius, draw_macro_flash
from gerberdiff.types import MacroAperture


def _make_ctx(w: int = 200, h: int = 200) -> tuple[cairo.Context, cairo.ImageSurface]:
    """1000 pixels/inch, Y-flipped, centred at (100, 100)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    ctx.translate(w / 2.0, h / 2.0)
    ctx.scale(1000.0, -1000.0)
    return ctx, surface


def _pixels_lit(surface: cairo.ImageSurface, w: int = 200, h: int = 200) -> int:
    arr = np.frombuffer(surface.get_data(), dtype=np.uint8).reshape(h, w, 4)
    return int(np.sum(arr[..., 3] > 0))


# ---------------------------------------------------------------------------
# Circle
# ---------------------------------------------------------------------------


def test_circle_macro_flash_produces_pixels() -> None:
    """0.05" radius circle macro at origin should produce non-zero pixels."""
    macro = parse_macro_body("C", "1,1,0.05,0,0,0")  # code, exposure, diam, cx, cy, rot
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


def test_circle_exposure_0_does_not_add_pixels() -> None:
    """Exposure=0 circle should erase pixels (DEST_OUT) -- surface stays blank."""
    macro = parse_macro_body("ZERO", "1,0,0.05,0,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    # Nothing was drawn first, so DEST_OUT on transparent = still transparent
    assert _pixels_lit(surface) == 0


# ---------------------------------------------------------------------------
# LineVector
# ---------------------------------------------------------------------------


def test_line_vector_macro_no_crash() -> None:
    # code=20, exposure=1, width=0.05, sx=-0.1, sy=0, ex=0.1, ey=0, rot=0
    macro = parse_macro_body("LV", "20,1,0.05,-0.1,0,0.1,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# LineCenter
# ---------------------------------------------------------------------------


def test_line_center_macro_no_crash() -> None:
    # code=21, exposure=1, width=0.1, height=0.05, cx=0, cy=0, rot=0
    macro = parse_macro_body("LC", "21,1,0.1,0.05,0,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------


def test_outline_macro_no_crash() -> None:
    # code=4, exposure=1, n_vertices=3, x0,y0,x1,y1,x2,y2, rot=0
    macro = parse_macro_body("OL", "4,1,3,0,0.1,0.1,-0.1,-0.1,-0.1,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    # Outline of a valid triangle should produce pixels
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# Polygon
# ---------------------------------------------------------------------------


def test_polygon_macro_no_crash() -> None:
    # code=5, exposure=1, n_vertices=6, cx=0, cy=0, diam=0.1, rot=0
    macro = parse_macro_body("PG", "5,1,6,0,0,0.1,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# Moire
# ---------------------------------------------------------------------------


def test_moire_macro_no_crash() -> None:
    # code=6, cx=0, cy=0, outer_diam=0.1, ring_thickness=0.01,
    #         ring_gap=0.01, max_rings=2, crosshair_thickness=0.005,
    #         crosshair_length=0.12, rot=0
    macro = parse_macro_body("MR", "6,0,0,0.1,0.01,0.01,2,0.005,0.12,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# Thermal
# ---------------------------------------------------------------------------


def test_thermal_macro_no_crash() -> None:
    # code=7, cx=0, cy=0, outer_diam=0.1, inner_diam=0.07, gap=0.02, rot=0
    macro = parse_macro_body("TH", "7,0,0,0.1,0.07,0.02,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, surface = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)
    assert _pixels_lit(surface) > 0


# ---------------------------------------------------------------------------
# Empty macro
# ---------------------------------------------------------------------------


def test_empty_macro_no_crash() -> None:
    macro = parse_macro_body("EMPTY", "")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, _ = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)  # must not raise


def test_none_macro_def_no_crash() -> None:
    aperture = MacroAperture(macro_def=None, params=[], unit_scale=1.0)
    ctx, _ = _make_ctx()
    draw_macro_flash(ctx, 0.0, 0.0, aperture)  # must not raise


# ---------------------------------------------------------------------------
# Bounding radius
# ---------------------------------------------------------------------------


def test_bounding_radius_circle() -> None:
    macro = parse_macro_body("C", "1,1,0.1,0,0,0")  # diameter=0.1 at origin
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    r = compute_macro_bounding_radius(aperture)
    assert abs(r - 0.05) < 1e-9


def test_bounding_radius_offset_circle() -> None:
    # Circle centred at (0.1, 0) with diameter 0.05 -> radius from origin = 0.1 + 0.025
    macro = parse_macro_body("C2", "1,1,0.05,0.1,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    r = compute_macro_bounding_radius(aperture)
    assert abs(r - 0.125) < 1e-9


def test_bounding_radius_unit_scale() -> None:
    macro = parse_macro_body("C", "1,1,0.1,0,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=0.5)
    r = compute_macro_bounding_radius(aperture)
    assert abs(r - 0.025) < 1e-9  # 0.05 * 0.5


def test_bounding_radius_none_macro() -> None:
    aperture = MacroAperture(macro_def=None, params=[], unit_scale=1.0)
    assert compute_macro_bounding_radius(aperture) == 0.0


# ---------------------------------------------------------------------------
# P5-2: draw_macro_flash evaluation failure emits UserWarning
# ---------------------------------------------------------------------------


def test_draw_macro_flash_evaluation_failure_emits_warning(monkeypatch) -> None:
    """When evaluate_macro_primitives raises, a UserWarning must be emitted."""
    import pytest

    import gerberdiff.render.macro_renderer as _mod

    macro = parse_macro_body("C", "1,1,0.05,0,0,0")
    aperture = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    ctx, _ = _make_ctx()

    def _raise(*_a, **_kw):
        raise ValueError("simulated evaluation failure")

    monkeypatch.setattr(_mod, "evaluate_macro_primitives", _raise)

    with pytest.warns(UserWarning, match="evaluation failed"):
        draw_macro_flash(ctx, 0.0, 0.0, aperture)


# ---------------------------------------------------------------------------
# P7-7: MacroAperture unit_scale renders smaller geometry
# ---------------------------------------------------------------------------


def test_macro_flash_mm_unit_scale_renders_smaller() -> None:
    """unit_scale=1/25.4 (mm->inch) renders a smaller circle than unit_scale=1.0."""
    macro = parse_macro_body("C", "1,1,0.05,0,0,0")  # 0.05" radius circle

    aperture_full = MacroAperture(macro_def=macro, params=[], unit_scale=1.0)
    aperture_small = MacroAperture(macro_def=macro, params=[], unit_scale=1.0 / 25.4)

    ctx_full, surface_full = _make_ctx()
    draw_macro_flash(ctx_full, 0.0, 0.0, aperture_full)

    ctx_small, surface_small = _make_ctx()
    draw_macro_flash(ctx_small, 0.0, 0.0, aperture_small)

    lit_full = _pixels_lit(surface_full)
    lit_small = _pixels_lit(surface_small)

    assert lit_full > 0, "unit_scale=1.0 produced no pixels"
    assert lit_small > 0, "unit_scale=1/25.4 produced no pixels"
    assert lit_small < lit_full, (
        f"unit_scale=1/25.4 ({lit_small} px) should render fewer pixels than "
        f"unit_scale=1.0 ({lit_full} px)"
    )
