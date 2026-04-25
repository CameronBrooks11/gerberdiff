"""Two-pass rasteriser: compile ParsedImage -> render to a Cairo surface.

Usage
-----
>>> from gerberdelta.render.renderer import render_to_surface, render_to_numpy
>>> from gerberdelta.render.viewport import compute_viewport
>>> vp = compute_viewport(parsed.bounding_box, width=1024, height=1024)
>>> surface = render_to_surface(parsed, vp)
>>> arr = render_to_numpy(parsed, vp)   # shape (H, W, 4) uint8 ARGB

Polarity
--------
Layers with ``Polarity.Dark`` are composited with OPERATOR_OVER.
Layers with ``Polarity.Clear`` are composited with OPERATOR_DEST_OUT, which
punches holes into previously drawn content.
"""

from __future__ import annotations

import math

import cairocffi as cairo
import numpy as np

from gerberdelta.render.compiled_render import (
    BlockFlash,
    CompiledGroup,
    CompiledLayer,
    FlashBatch,
    HoledFlash,
    MacroFlash,
    RegionGroup,
    StrokeBatch,
    compile_render,
)
from gerberdelta.render.draw_ops import (
    draw_flash,
    draw_net_as_stroke,
    draw_net_segment_in_region,
)
from gerberdelta.render.macro_renderer import draw_macro_flash
from gerberdelta.render.viewport import Viewport
from gerberdelta.types import (
    Aperture,
    BlockAperture,
    CoordState,
    MacroAperture,
    MirrorState,
    ParsedImage,
    Polarity,
)

# Default draw colour: bright green (matches reference tool palette).
_DEFAULT_COLOR: tuple[float, float, float, float] = (0.0, 1.0, 0.533, 1.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_to_surface(
    parsed_image: ParsedImage,
    viewport: Viewport,
    draw_color: tuple[float, float, float, float] = _DEFAULT_COLOR,
    coordinate_offset: tuple[float, float] | None = None,
) -> cairo.ImageSurface:
    """Render *parsed_image* into a new ``cairo.ImageSurface``.

    The surface uses ``FORMAT_ARGB32`` (premultiplied alpha).  Transparent
    pixels represent the PCB substrate / background.

    *coordinate_offset* shifts the board in world-space (inches) before
    rendering.  Used by ``compute_diff`` to align two boards with different
    origins.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, viewport.width, viewport.height)
    ctx = cairo.Context(surface)

    # Start with a fully transparent canvas.
    ctx.set_operator(cairo.OPERATOR_CLEAR)
    ctx.paint()
    ctx.set_operator(cairo.OPERATOR_OVER)

    # Apply viewport transform: pan, then Y-flip + zoom so Gerber's
    # mathematical Y-up coordinate system maps to screen Y-down.
    ctx.save()
    ctx.translate(viewport.pan_x, viewport.pan_y)
    ctx.scale(viewport.zoom, -viewport.zoom)
    if coordinate_offset is not None:
        ctx.translate(coordinate_offset[0], coordinate_offset[1])
    # Global draw style.
    ctx.set_source_rgba(*draw_color)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)

    cr = compile_render(parsed_image)
    for layer in cr.layers:
        _render_layer(ctx, layer, parsed_image.apertures)

    ctx.restore()
    return surface


def render_to_numpy(
    parsed_image: ParsedImage,
    viewport: Viewport,
    draw_color: tuple[float, float, float, float] = _DEFAULT_COLOR,
    coordinate_offset: tuple[float, float] | None = None,
) -> np.ndarray:
    """Render to a ``numpy`` array of shape ``(H, W, 4)`` with dtype ``uint8``.

    Channel order is BGRA (Cairo's native ARGB32 little-endian layout).
    """
    surface = render_to_surface(parsed_image, viewport, draw_color, coordinate_offset)
    surface.flush()
    buf = surface.get_data()
    arr = np.frombuffer(buf, dtype=np.uint8)
    # copy() transfers ownership away from the cairo surface buffer so the
    # returned array remains valid after the surface is garbage-collected.
    return arr.reshape(viewport.height, viewport.width, 4).copy()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_layer(
    ctx: cairo.Context,
    layer: CompiledLayer,
    apertures: dict[int, Aperture],
    depth: int = 0,
) -> None:
    """Render one compiled layer, applying polarity, transforms, and SR."""
    ctx.save()

    # Polarity: clear layers punch holes via DEST_OUT.
    if layer.polarity == Polarity.Clear:
        ctx.set_operator(cairo.OPERATOR_DEST_OUT)

    # Optional layer-level transforms.
    # Cairo post-multiplies each call into the CTM, so the last call in code
    # is the FIRST transform applied to coordinates.  RS-274X §4.9 specifies
    # that coordinates are transformed as: scale → rotation → mirror.
    # Code order must therefore be the reverse: mirror → rotation → scale.
    if layer.mirror != MirrorState.None_:
        sx = -1.0 if layer.mirror in (MirrorState.FlipA, MirrorState.FlipAB) else 1.0
        sy = -1.0 if layer.mirror in (MirrorState.FlipB, MirrorState.FlipAB) else 1.0
        ctx.scale(sx, sy)
    if layer.rotation != 0.0:
        ctx.rotate(math.radians(layer.rotation))
    if layer.scale != 1.0:
        ctx.scale(layer.scale, layer.scale)

    # Step-and-repeat: only loop when SR counts exceed 1.
    sr = layer.step_and_repeat
    if sr.x > 1 or sr.y > 1:
        for ix in range(sr.x):
            for iy in range(sr.y):
                ctx.save()
                ctx.translate(ix * sr.dist_x, iy * sr.dist_y)
                _render_groups(ctx, layer.groups, apertures, depth)
                ctx.restore()
    else:
        _render_groups(ctx, layer.groups, apertures, depth)

    ctx.restore()


def _render_groups(
    ctx: cairo.Context,
    groups: list[CompiledGroup],
    apertures: dict[int, Aperture],
    depth: int = 0,
) -> None:
    """Execute each compiled group against *ctx*."""
    for group in groups:
        match group:
            case FlashBatch():
                ap = apertures.get(group.aperture_code)
                for net in group.nets:
                    draw_flash(ctx, net, ap)

            case StrokeBatch():
                ap = apertures.get(group.aperture_code)
                for net in group.nets:
                    draw_net_as_stroke(ctx, net, ap)

            case RegionGroup():
                ctx.save()
                ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
                ctx.new_path()
                for net in group.nets:
                    draw_net_segment_in_region(ctx, net)
                ctx.close_path()
                ctx.fill()
                ctx.restore()

            case HoledFlash():
                if group.net is not None:
                    ap = apertures.get(group.aperture_code)
                    draw_flash(ctx, group.net, ap)

            case MacroFlash():
                if group.net is not None:
                    ap = apertures.get(group.aperture_code)
                    if isinstance(ap, MacroAperture):
                        draw_macro_flash(
                            ctx,
                            group.net.stop_x,
                            group.net.stop_y,
                            ap,
                        )

            case BlockFlash():
                if group.net is not None:
                    ap = apertures.get(group.aperture_code)
                    if isinstance(ap, BlockAperture):
                        _draw_block_flash(
                            ctx,
                            group.net.stop_x,
                            group.net.stop_y,
                            ap,
                            depth + 1,
                        )


def _draw_block_flash(
    ctx: cairo.Context,
    x: float,
    y: float,
    block_ap: BlockAperture,
    depth: int = 0,
) -> None:
    """Render a block aperture flash by recursively compiling and drawing it.

    The block's nets are in its own coordinate system.  Translating by
    ``(x, y)`` stamps the block at the flash position.

    *depth* tracks the block-nesting level.  Rendering is silently skipped
    when ``depth >= 10``, matching the parser's nesting limit and preventing
    unbounded recursion on malformed input.
    """
    if depth >= 10:
        return
    if not block_ap.draw_ops:
        return

    # Build a minimal synthetic ParsedImage so compile_render can be reused.
    # Layer states come from the block's own captured layers (at least one).
    layers = block_ap.layers if block_ap.layers else []
    synthetic = ParsedImage(
        draw_ops=block_ap.draw_ops,
        apertures=block_ap.apertures,
        layers=layers,
        coord_states=[CoordState()],
        bounding_box=block_ap.bounding_box,
        diagnostics=[],
    )

    ctx.save()
    ctx.translate(x, y)
    cr = compile_render(synthetic)
    for layer in cr.layers:
        _render_layer(ctx, layer, block_ap.apertures, depth)
    ctx.restore()
