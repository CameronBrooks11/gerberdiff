"""Tests for the compiled-render pass and the Cairo rasteriser."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gerberdiff.parse.gerber_state import parse_gerber
from gerberdiff.render.compiled_render import (
    CompiledRender,
    FlashBatch,
    HoledFlash,
    MacroFlash,
    RegionGroup,
    StrokeBatch,
    compile_render,
)
from gerberdiff.render.renderer import render_to_numpy, render_to_surface
from gerberdiff.render.viewport import Viewport, compute_viewport
from gerberdiff.types import (
    Aperture,
    ApertureState,
    BlockAperture,
    BoundingBox,
    CircleAperture,
    DrawOp,
    InterpolationMode,
    LayerState,
    MacroAperture,
    MirrorState,
    ParsedImage,
    Polarity,
    RegionFill,
    StepAndRepeat,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "gerbers-before"

_FCU = _FIXTURES / "A64-OlinuXino-F.Cu.gbr"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_image() -> ParsedImage:
    return ParsedImage(
        draw_ops=[],
        apertures={},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=BoundingBox(),
        diagnostics=[],
    )


def _net(
    *,
    aperture_index: int = 10,
    aperture_state: ApertureState = ApertureState.Flash,
    stop_x: float = 0.1,
    stop_y: float = 0.1,
    layer_index: int = 0,
) -> DrawOp:
    return DrawOp(
        start_x=stop_x,
        start_y=stop_y,
        stop_x=stop_x,
        stop_y=stop_y,
        aperture_index=aperture_index,
        aperture_state=aperture_state,
        interpolation=InterpolationMode.Linear,
        layer_index=layer_index,
        net_state_index=0,
    )


def _image_with_nets(
    nets: list[DrawOp | RegionFill], apertures: dict[int, Aperture] | None = None
) -> ParsedImage:
    bb = BoundingBox()
    for n in nets:
        if isinstance(n, DrawOp):
            bb.expand(n.stop_x, n.stop_y)
        else:
            for s in n.segments:
                bb.expand(s.stop_x, s.stop_y)
    return ParsedImage(
        draw_ops=nets,
        apertures=apertures or {10: CircleAperture(diameter=0.01)},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )


# ---------------------------------------------------------------------------
# compile_render tests
# ---------------------------------------------------------------------------


def test_compile_empty_image() -> None:
    cr = compile_render(_empty_image())
    assert isinstance(cr, CompiledRender)
    assert len(cr.layers) == 1
    assert len(cr.layers[0].groups) == 0


def test_compile_flash_batch_groups_by_aperture() -> None:
    """Three flashes on the same aperture -> one FlashBatch with three nets."""
    nets: list[DrawOp | RegionFill] = [
        _net(aperture_index=10, aperture_state=ApertureState.Flash, stop_x=0.1),
        _net(aperture_index=10, aperture_state=ApertureState.Flash, stop_x=0.2),
        _net(aperture_index=10, aperture_state=ApertureState.Flash, stop_x=0.3),
    ]
    cr = compile_render(_image_with_nets(nets))
    groups = cr.layers[0].groups
    assert len(groups) == 1
    assert isinstance(groups[0], FlashBatch)
    assert groups[0].aperture_code == 10
    assert len(groups[0].nets) == 3


def test_compile_flash_batch_splits_on_aperture_change() -> None:
    """Two different apertures -> two FlashBatch groups."""
    nets: list[DrawOp | RegionFill] = [
        _net(aperture_index=10, aperture_state=ApertureState.Flash, stop_x=0.1),
        _net(aperture_index=11, aperture_state=ApertureState.Flash, stop_x=0.2),
    ]
    aps: dict[int, Aperture] = {
        10: CircleAperture(diameter=0.01),
        11: CircleAperture(diameter=0.02),
    }
    cr = compile_render(_image_with_nets(nets, aps))
    groups = cr.layers[0].groups
    assert len(groups) == 2
    assert all(isinstance(g, FlashBatch) for g in groups)


def test_compile_stroke_batch() -> None:
    """Consecutive On-state nets -> one StrokeBatch."""
    nets: list[DrawOp | RegionFill] = [
        _net(aperture_index=10, aperture_state=ApertureState.On, stop_x=0.1),
        _net(aperture_index=10, aperture_state=ApertureState.On, stop_x=0.2),
    ]
    cr = compile_render(_image_with_nets(nets))
    groups = cr.layers[0].groups
    assert len(groups) == 1
    assert isinstance(groups[0], StrokeBatch)
    assert len(groups[0].nets) == 2


def test_compile_region_group() -> None:
    """RegionFill in draw_ops -> one RegionGroup with the region's segments."""
    segments = [
        _net(aperture_state=ApertureState.On, stop_x=0.1),
        _net(aperture_state=ApertureState.On, stop_x=0.2),
    ]
    region = RegionFill(layer_index=0, net_state_index=0, segments=segments)
    cr = compile_render(_image_with_nets([region]))
    groups = cr.layers[0].groups
    assert len(groups) == 1
    assert isinstance(groups[0], RegionGroup)
    assert len(groups[0].nets) == 2


def test_compile_holed_flash() -> None:
    """Flash on an aperture with hole_diameter set -> HoledFlash."""
    nets: list[DrawOp | RegionFill] = [_net(aperture_index=10, aperture_state=ApertureState.Flash)]
    aps: dict[int, Aperture] = {10: CircleAperture(diameter=0.05, hole_diameter=0.02)}
    cr = compile_render(_image_with_nets(nets, aps))
    groups = cr.layers[0].groups
    assert len(groups) == 1
    assert isinstance(groups[0], HoledFlash)
    assert groups[0].net is nets[0]


def test_compile_macro_flash() -> None:
    """Flash on a MacroAperture -> MacroFlash."""
    nets: list[DrawOp | RegionFill] = [_net(aperture_index=10, aperture_state=ApertureState.Flash)]
    aps: dict[int, Aperture] = {10: MacroAperture()}
    cr = compile_render(_image_with_nets(nets, aps))
    groups = cr.layers[0].groups
    assert len(groups) == 1
    assert isinstance(groups[0], MacroFlash)


def test_compile_off_state_flushes_stroke() -> None:
    """D02 move between strokes produces two separate StrokeBatch groups."""
    nets: list[DrawOp | RegionFill] = [
        _net(aperture_index=10, aperture_state=ApertureState.On, stop_x=0.1),
        _net(aperture_index=10, aperture_state=ApertureState.Off, stop_x=0.2),
        _net(aperture_index=10, aperture_state=ApertureState.On, stop_x=0.3),
    ]
    cr = compile_render(_image_with_nets(nets))
    groups = cr.layers[0].groups
    assert len(groups) == 2
    assert all(isinstance(g, StrokeBatch) for g in groups)


def test_compile_preserves_layer_polarity() -> None:
    """CompiledLayer polarity matches the source LayerState polarity."""
    cr = compile_render(_empty_image())
    assert cr.layers[0].polarity == Polarity.Dark


def test_compile_step_and_repeat_preserved() -> None:
    """StepAndRepeat from LayerState is forwarded to CompiledLayer."""
    sr = StepAndRepeat(x=3, y=2, dist_x=0.5, dist_y=0.5)
    image = _empty_image()
    image.layers[0].step_and_repeat = sr
    cr = compile_render(image)
    assert cr.layers[0].step_and_repeat.x == 3
    assert cr.layers[0].step_and_repeat.y == 2


# ---------------------------------------------------------------------------
# renderer tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_fcu_has_nonzero_pixels() -> None:
    """F.Cu renders with visible content at 1024x1024."""
    parsed = parse_gerber(_FCU.read_text(encoding="utf-8"), source_path=_FCU)
    vp = compute_viewport(parsed.bounding_box, 1024, 1024)
    arr = render_to_numpy(parsed, vp)
    alpha = arr[:, :, 3]
    assert int(np.sum(alpha > 0)) > 10_000


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_to_numpy_shape() -> None:
    """render_to_numpy returns correct shape and dtype."""
    parsed = parse_gerber(_FCU.read_text(encoding="utf-8"), source_path=_FCU)
    vp = compute_viewport(parsed.bounding_box, 512, 512)
    arr = render_to_numpy(parsed, vp)
    assert arr.shape == (512, 512, 4)
    assert arr.dtype == np.uint8


def test_render_empty_gerber_no_crash() -> None:
    """Rendering an image with no nets completes without error."""
    import cairocffi as cairo

    image = _empty_image()
    vp = compute_viewport(image.bounding_box, 100, 100)
    surface = render_to_surface(image, vp)
    assert isinstance(surface, cairo.ImageSurface)
    # Fully transparent canvas -- all bytes zero.
    surface.flush()
    buf = bytes(surface.get_data())
    assert all(b == 0 for b in buf)


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_consistent_with_viewport() -> None:
    """Content stays within viewport margins: border pixels are mostly blank."""
    parsed = parse_gerber(_FCU.read_text(encoding="utf-8"), source_path=_FCU)
    vp = compute_viewport(parsed.bounding_box, 1024, 1024)
    arr = render_to_numpy(parsed, vp)
    alpha = arr[:, :, 3]

    # Build a mask of the 1-pixel border.
    border = np.zeros((1024, 1024), dtype=bool)
    border[0, :] = True
    border[-1, :] = True
    border[:, 0] = True
    border[:, -1] = True

    lit_border = int(np.sum(alpha[border] > 0))
    assert lit_border < 100


# ---------------------------------------------------------------------------
# 3.1 -- Cairo layer transform order (RS-274X sec.4.9)
# ---------------------------------------------------------------------------


def _flash_at(x: float, y: float, layer: LayerState | None = None) -> ParsedImage:
    """Minimal ParsedImage with one circle flash at (x, y)."""
    ap_code = 10
    net = DrawOp(
        start_x=x,
        start_y=y,
        stop_x=x,
        stop_y=y,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(x, y, 0.02)
    return ParsedImage(
        draw_ops=[net],
        apertures={ap_code: CircleAperture(diameter=0.04)},
        layers=[layer or LayerState()],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )


def test_layer_transform_order_rotation_plus_mirror() -> None:
    """RS-274X sec.4.9: coordinates transform as scale->rotation->mirror.

    A flash at (0.5, 0.0) with rotation=90deg and mirror=FlipA:
      Correct order  (applied to coords): scale(noop)->rotate90->flipA
        (0.5,0) -> rotate90 -> (0,0.5) -> flipA (x->-x) -> (0,0.5) -> screen y < 50
      Wrong order (applied to coords): flipA->rotate90->scale
        (0.5,0) -> flipA -> (-0.5,0) -> rotate90 -> (0,-0.5) -> screen y > 50
    """
    # Fixed viewport: origin at pixel (50,50), 40 px/inch.
    vp = Viewport(width=100, height=100, pan_x=50.0, pan_y=50.0, zoom=40.0)
    img = _flash_at(0.5, 0.0, LayerState(rotation=90.0, mirror=MirrorState.FlipA))
    arr = render_to_numpy(img, vp)
    alpha = arr[:, :, 3]
    lit = np.argwhere(alpha > 0)
    assert len(lit) > 0, "No pixels rendered -- aperture/viewport mismatch"
    y_centroid = float(np.mean(lit[:, 0]))  # row 0 = top of screen
    # Correct: flash ends at Gerber (0, 0.5) -> screen y = 50 - 0.5*40 = 30 (above centre)
    # Wrong:   flash ends at Gerber (0, -0.5) -> screen y = 50 + 0.5*40 = 70 (below centre)
    assert y_centroid < 50.0, (
        f"Transform order wrong: centroid y={y_centroid:.1f} expected < 50 (above centre)"
    )


def test_layer_transform_no_transforms_unchanged() -> None:
    """A layer with no transforms renders at the unmodified position."""
    vp = Viewport(width=100, height=100, pan_x=50.0, pan_y=50.0, zoom=40.0)
    img = _flash_at(0.5, 0.0)  # no transforms
    arr = render_to_numpy(img, vp)
    alpha = arr[:, :, 3]
    lit = np.argwhere(alpha > 0)
    assert len(lit) > 0
    x_centroid = float(np.mean(lit[:, 1]))  # col index = x in screen
    # Flash at (0.5, 0.0) -> screen x = 50 + 0.5*40 = 70 (right of centre)
    assert x_centroid > 50.0, f"Flash should be right of centre, got x={x_centroid:.1f}"


# ---------------------------------------------------------------------------
# 3.2 -- Block aperture recursion depth guard
# ---------------------------------------------------------------------------


def _make_nested_block(nesting: int) -> BlockAperture:
    """Build a chain of BlockApertures *nesting* levels deep."""
    ap_code = 1
    net = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(0.0, 0.0, 0.005)
    if nesting == 0:
        return BlockAperture(
            draw_ops=[net],
            apertures={ap_code: CircleAperture(diameter=0.01)},
            layers=[LayerState()],
            bounding_box=bb,
        )
    inner = _make_nested_block(nesting - 1)
    return BlockAperture(
        draw_ops=[net],
        apertures={ap_code: inner},
        layers=[LayerState()],
        bounding_box=bb,
    )


def test_block_flash_depth_guard_no_recursion_error() -> None:
    """A 15-level nested BlockAperture completes without RecursionError."""
    outermost = _make_nested_block(15)
    ap_code = 1
    net = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(0.0, 0.0, 0.005)
    img = ParsedImage(
        draw_ops=[net],
        apertures={ap_code: outermost},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )
    vp = Viewport(width=50, height=50, pan_x=25.0, pan_y=25.0, zoom=200.0)
    arr = render_to_numpy(img, vp)  # must not raise
    assert arr.shape == (50, 50, 4)


# ---------------------------------------------------------------------------
# P7-2: Step-and-repeat rendering
# ---------------------------------------------------------------------------


def test_sr_render_produces_multiple_instances() -> None:
    """An SR X2 layer must render the flash geometry twice at different positions."""
    ap_code = 10
    net = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(0.0, 0.0, 0.02)
    bb.expand(0.5, 0.0, 0.02)  # second instance at x=0.5
    # SR: 2 steps in X, 1 step in Y, 0.5 inch apart.
    layer = LayerState(step_and_repeat=StepAndRepeat(x=2, y=1, dist_x=0.5, dist_y=0.0))
    img = ParsedImage(
        draw_ops=[net],
        apertures={ap_code: CircleAperture(diameter=0.04)},
        layers=[layer],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )
    # Viewport covers both instances: 1 inch wide at 100 px/inch -> 100 px
    vp = Viewport(width=100, height=50, pan_x=50.0, pan_y=25.0, zoom=100.0)
    arr = render_to_numpy(img, vp)
    alpha = arr[:, :, 3]
    # Find columns with any lit pixels
    lit_cols = np.where(np.any(alpha > 0, axis=0))[0]
    assert len(lit_cols) > 0, "No pixels rendered"
    col_min, col_max = int(lit_cols.min()), int(lit_cols.max())
    # Two instances separated by 50 px (0.5 inch x 100 px/inch) -- range must span > 20 px
    assert col_max - col_min > 20, (
        f"SR X2 instances too close together: col range [{col_min}, {col_max}]"
    )


# ---------------------------------------------------------------------------
# P7-3: Layer scale transform
# ---------------------------------------------------------------------------


def test_ls_scale_changes_pixel_count() -> None:
    """LayerState(scale=2.0) renders a larger flash than scale=1.0."""
    ap_code = 10
    # Shared net: flash at origin
    net = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(0.0, 0.0, 0.1)
    apertures = {ap_code: CircleAperture(diameter=0.1)}
    vp = Viewport(width=64, height=64, pan_x=32.0, pan_y=32.0, zoom=200.0)

    def _render_with_scale(s: float) -> int:
        img = ParsedImage(
            draw_ops=[net],
            apertures=apertures,
            layers=[LayerState(scale=s)],
            coord_states=[],
            bounding_box=bb,
            diagnostics=[],
        )
        arr = render_to_numpy(img, vp)
        return int(np.sum(arr[:, :, 3] > 0))

    pixels_1x = _render_with_scale(1.0)
    pixels_2x = _render_with_scale(2.0)
    assert pixels_1x > 0, "scale=1.0 produced no pixels"
    assert pixels_2x > pixels_1x, (
        f"scale=2.0 ({pixels_2x} px) should produce more pixels than scale=1.0 ({pixels_1x} px)"
    )


# ---------------------------------------------------------------------------
# P7-4: Clear polarity erases geometry
# ---------------------------------------------------------------------------


def test_clear_polarity_erases_geometry() -> None:
    """A clear-polarity flash at the same location as a dark flash erases pixels."""
    ap_code = 10
    # Flash at origin on layer 0 (dark) and layer 1 (clear).
    net_dark = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    net_clear = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=0.0,
        stop_y=0.0,
        aperture_index=ap_code,
        aperture_state=ApertureState.Flash,
        interpolation=InterpolationMode.Linear,
        layer_index=1,
        net_state_index=0,
    )
    bb = BoundingBox()
    bb.expand(0.0, 0.0, 0.1)
    apertures = {ap_code: CircleAperture(diameter=0.1)}
    vp = Viewport(width=64, height=64, pan_x=32.0, pan_y=32.0, zoom=300.0)

    # Dark only: has lit pixels
    img_dark = ParsedImage(
        draw_ops=[net_dark],
        apertures=apertures,
        layers=[LayerState(polarity=Polarity.Dark)],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )
    arr_dark = render_to_numpy(img_dark, vp)
    dark_pixels = int(np.sum(arr_dark[:, :, 3] > 0))
    assert dark_pixels > 0, "Dark-polarity flash produced no pixels"

    # Dark + clear at same location: clear layer erases the dark pixels
    img_both = ParsedImage(
        draw_ops=[net_dark, net_clear],
        apertures=apertures,
        layers=[LayerState(polarity=Polarity.Dark), LayerState(polarity=Polarity.Clear)],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )
    arr_both = render_to_numpy(img_both, vp)
    both_pixels = int(np.sum(arr_both[:, :, 3] > 0))
    assert both_pixels < dark_pixels, (
        f"Clear polarity should erase pixels: dark={dark_pixels}, after_clear={both_pixels}"
    )
