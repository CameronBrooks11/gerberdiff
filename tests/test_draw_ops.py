from __future__ import annotations

import cairocffi as cairo

from gerberdelta.render.draw_ops import draw_arc_path, draw_flash, draw_net_as_stroke
from gerberdelta.types import (
    ApertureState,
    ArcSegment,
    CircleAperture,
    InterpolationMode,
    Net,
    ObroundAperture,
    PolygonAperture,
    RectangleAperture,
)


def _make_ctx(w: int = 100, h: int = 100) -> tuple[cairo.Context, cairo.ImageSurface]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(surface)
    ctx.scale(10.0, -10.0)
    ctx.translate(0.0, -float(h) / 10.0)
    ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    return ctx, surface


def _flash_net() -> Net:
    return Net(
        start_x=0.0, start_y=0.0,
        stop_x=5.0, stop_y=5.0,
        aperture_index=10,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )


def _stroke_net() -> Net:
    return Net(
        start_x=1.0, start_y=1.0,
        stop_x=4.0, stop_y=4.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )


# ---- flash tests ----

def test_circle_flash_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), CircleAperture(diameter=0.5))


def test_circle_flash_with_hole_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), CircleAperture(diameter=0.5, hole_diameter=0.2))


def test_rectangle_flash_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), RectangleAperture(width=0.5, height=0.3))


def test_rectangle_flash_with_hole_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), RectangleAperture(width=0.5, height=0.3, hole_diameter=0.1))


def test_obround_flash_wide_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), ObroundAperture(width=0.5, height=0.2))


def test_obround_flash_tall_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), ObroundAperture(width=0.2, height=0.5))


def test_polygon_flash_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), PolygonAperture(outer_diameter=0.5, num_vertices=6))


def test_flash_none_aperture_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_flash(ctx, _flash_net(), None)


# ---- stroke tests ----

def test_stroke_circle_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_net_as_stroke(ctx, _stroke_net(), CircleAperture(diameter=0.1))


def test_stroke_rectangle_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_net_as_stroke(ctx, _stroke_net(), RectangleAperture(width=0.2, height=0.1))


def test_stroke_none_aperture_no_crash() -> None:
    ctx, _ = _make_ctx()
    draw_net_as_stroke(ctx, _stroke_net(), None)


# ---- arc tests ----

def test_arc_path_ccw_no_crash() -> None:
    ctx, _ = _make_ctx()
    arc = ArcSegment(center_x=5.0, center_y=5.0, radius=2.0, start_angle_deg=0.0, end_angle_deg=90.0)
    ctx.new_path()
    draw_arc_path(ctx, arc, clockwise=False)


def test_arc_path_cw_no_crash() -> None:
    ctx, _ = _make_ctx()
    arc = ArcSegment(center_x=5.0, center_y=5.0, radius=2.0, start_angle_deg=90.0, end_angle_deg=0.0)
    ctx.new_path()
    draw_arc_path(ctx, arc, clockwise=True)
