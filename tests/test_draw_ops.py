from __future__ import annotations

import cairocffi as cairo

from gerberdelta.render.draw_ops import draw_arc_path, draw_flash, draw_net_as_stroke
from gerberdelta.types import (
    ApertureState,
    ArcSegment,
    CircleAperture,
    DrawOp,
    InterpolationMode,
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


def _flash_net() -> DrawOp:
    return DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=5.0,
        stop_y=5.0,
        aperture_index=10,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )


def _stroke_net() -> DrawOp:
    return DrawOp(
        start_x=1.0,
        start_y=1.0,
        stop_x=4.0,
        stop_y=4.0,
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


def test_stroke_obround_produces_visible_pixels() -> None:
    """ObroundAperture stroke uses min(w,h) line width — not the 0.001 hairline."""
    import numpy as np

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    ctx = cairo.Context(surface)
    # 50 px/unit scale, origin at centre.
    ctx.translate(50.0, 50.0)
    ctx.scale(50.0, -50.0)
    ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    net = DrawOp(
        start_x=-0.5,
        start_y=0.0,
        stop_x=0.5,
        stop_y=0.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    draw_net_as_stroke(ctx, net, ObroundAperture(width=0.4, height=0.2))
    surface.flush()
    buf = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(100, 100, 4)
    lit = int(np.sum(buf[:, :, 3] > 0))
    # 0.2 inch at 50 px/inch = 10 px diameter; stroke length ~50 px -> > 200 px expected
    assert lit > 200, f"ObroundAperture stroke too thin: only {lit} lit pixels"


def test_stroke_polygon_produces_visible_pixels() -> None:
    """PolygonAperture stroke uses outer_diameter — not the 0.001 hairline."""
    import numpy as np

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    ctx = cairo.Context(surface)
    ctx.translate(50.0, 50.0)
    ctx.scale(50.0, -50.0)
    ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    net = DrawOp(
        start_x=-0.5,
        start_y=0.0,
        stop_x=0.5,
        stop_y=0.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    draw_net_as_stroke(ctx, net, PolygonAperture(outer_diameter=0.2, num_vertices=6))
    surface.flush()
    buf = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(100, 100, 4)
    lit = int(np.sum(buf[:, :, 3] > 0))
    assert lit > 200, f"PolygonAperture stroke too thin: only {lit} lit pixels"


# ---- arc tests ----


def test_arc_path_ccw_no_crash() -> None:
    ctx, _ = _make_ctx()
    arc = ArcSegment(
        center_x=5.0, center_y=5.0, radius=2.0, start_angle_deg=0.0, end_angle_deg=90.0
    )
    ctx.new_path()
    draw_arc_path(ctx, arc, clockwise=False)


def test_arc_path_cw_no_crash() -> None:
    ctx, _ = _make_ctx()
    arc = ArcSegment(
        center_x=5.0, center_y=5.0, radius=2.0, start_angle_deg=90.0, end_angle_deg=0.0
    )
    ctx.new_path()
    draw_arc_path(ctx, arc, clockwise=True)


# ---------------------------------------------------------------------------
# P5-1: Rectangle and obround stroke width uses max(w, h)
# ---------------------------------------------------------------------------


def _count_lit_pixels(surface: cairo.ImageSurface, w: int, h: int) -> int:
    import numpy as np

    surface.flush()
    buf = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(h, w, 4)
    return int(np.sum(buf[:, :, 3] > 0))


def _stroke_surface(aperture, width: int = 100, height: int = 100) -> int:
    """Return the number of lit pixels when stroking a horizontal line."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.translate(width / 2.0, height / 2.0)
    ctx.scale(50.0, -50.0)
    ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    net = DrawOp(
        start_x=-0.5,
        start_y=0.0,
        stop_x=0.5,
        stop_y=0.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    draw_net_as_stroke(ctx, net, aperture)
    return _count_lit_pixels(surface, width, height)


def test_rectangle_stroke_wide_aperture_produces_wider_stroke_than_narrow() -> None:
    """max(w,h) ensures the wide dimension is used for the stroke width.

    RectangleAperture(0.5, 0.1): max=0.5 → 25 px wide at 50 px/inch.
    RectangleAperture(0.1, 0.5): max=0.5 → same 25 px wide.
    Both should produce far more pixels than CircleAperture(diameter=0.1) → 5 px.
    """
    wide_horizontal = _stroke_surface(RectangleAperture(width=0.5, height=0.1))
    wide_vertical = _stroke_surface(RectangleAperture(width=0.1, height=0.5))
    narrow_reference = _stroke_surface(CircleAperture(diameter=0.1))

    assert wide_horizontal > narrow_reference * 3, (
        f"wide_horizontal={wide_horizontal} should be >> narrow={narrow_reference}"
    )
    assert wide_vertical > narrow_reference * 3, (
        f"wide_vertical={wide_vertical} should be >> narrow={narrow_reference}"
    )


def test_obround_stroke_wide_aperture_uses_max_dimension() -> None:
    """ObroundAperture(0.4, 0.1): max=0.4 → wider stroke than CircleAperture(0.1)."""
    wide = _stroke_surface(ObroundAperture(width=0.4, height=0.1))
    narrow = _stroke_surface(CircleAperture(diameter=0.1))
    assert wide > narrow * 2, f"wide={wide} should be >> narrow={narrow}"


# ---------------------------------------------------------------------------
# P7-6: PolygonAperture rotation shifts vertex positions
# ---------------------------------------------------------------------------


def test_polygon_flash_rotation_shifts_vertex_positions() -> None:
    """A triangle at rotation=0 and rotation=60 deg render different pixel sets."""
    import numpy as np

    # Flash at origin (0, 0); ctx places origin at centre of 100×100 canvas.
    origin_net = DrawOp(
        start_x=0.0, start_y=0.0, stop_x=0.0, stop_y=0.0,
        aperture_index=10, aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear, layer_index=0, net_state_index=0,
    )

    def _render_triangle(rotation_deg: float) -> np.ndarray:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
        ctx = cairo.Context(surface)
        ctx.translate(50.0, 50.0)
        ctx.scale(50.0, -50.0)
        ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0)
        draw_flash(ctx, origin_net, PolygonAperture(outer_diameter=0.8, num_vertices=3, rotation=rotation_deg))
        surface.flush()
        return np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(100, 100, 4)

    arr0 = _render_triangle(0.0)
    arr60 = _render_triangle(60.0)

    # Both renders must have some lit pixels.
    assert arr0[:, :, 3].max() > 0, "rotation=0 produced no pixels"
    assert arr60[:, :, 3].max() > 0, "rotation=60 produced no pixels"

    # The two renders must differ (rotation moves the triangle vertices).
    diff = np.any(arr0 != arr60, axis=-1)
    assert diff.any(), "rotation=0 and rotation=60 produced identical pixels"


# ---------------------------------------------------------------------------
# P7-12: Pixel verification for existing flash tests
# ---------------------------------------------------------------------------


def _read_pixels(surface: cairo.ImageSurface, w: int = 100, h: int = 100) -> "np.ndarray":
    import numpy as np
    surface.flush()
    return np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(h, w, 4)


def test_circle_flash_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_flash(ctx, _flash_net(), CircleAperture(diameter=0.5))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "CircleAperture flash produced no pixels"


def test_rectangle_flash_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_flash(ctx, _flash_net(), RectangleAperture(width=0.5, height=0.3))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "RectangleAperture flash produced no pixels"


def test_obround_flash_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_flash(ctx, _flash_net(), ObroundAperture(width=0.5, height=0.2))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "ObroundAperture flash produced no pixels"


def test_polygon_flash_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_flash(ctx, _flash_net(), PolygonAperture(outer_diameter=0.5, num_vertices=6))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "PolygonAperture flash produced no pixels"


def test_stroke_circle_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_net_as_stroke(ctx, _stroke_net(), CircleAperture(diameter=0.1))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "CircleAperture stroke produced no pixels"


def test_stroke_rectangle_produces_pixels() -> None:
    ctx, surface = _make_ctx()
    draw_net_as_stroke(ctx, _stroke_net(), RectangleAperture(width=0.2, height=0.1))
    arr = _read_pixels(surface)
    assert arr[:, :, 3].max() > 0, "RectangleAperture stroke produced no pixels"
