"""Tests for block aperture parsing (%AB%) and rendering (BlockFlash)."""

from __future__ import annotations

import numpy as np

from gerberdelta.parse.gerber_state import parse_gerber
from gerberdelta.render.compiled_render import BlockFlash, compile_render
from gerberdelta.render.renderer import render_to_numpy, render_to_surface
from gerberdelta.render.viewport import compute_viewport
from gerberdelta.types import (
    ApertureState,
    BlockAperture,
    BoundingBox,
    CircleAperture,
    CoordState,
    DrawOp,
    LayerState,
    ParsedImage,
)

# ---------------------------------------------------------------------------
# Minimal gerber helpers
# ---------------------------------------------------------------------------

_HEADER = """\
%FSLAX25Y25*%
%MOIN*%
"""

_FOOTER = "M02*\n"


def _gerber(*body_lines: str) -> str:
    return _HEADER + "\n".join(body_lines) + "\n" + _FOOTER


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


def test_block_aperture_parsed_and_registered() -> None:
    """A block aperture defined with %ABD10*% ... %AB*% appears in apertures."""
    src = _gerber(
        "%ADD11C,0.1*%",  # circle aperture in the block
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",  # flash inside block
        "%AB*%",
    )
    img = parse_gerber(src)
    assert 10 in img.apertures
    ap = img.apertures[10]
    assert isinstance(ap, BlockAperture)


def test_block_aperture_nets_captured() -> None:
    """Nets emitted inside the block end up in BlockAperture.nets."""
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",
        "X10000Y00000D03*",
        "%AB*%",
    )
    img = parse_gerber(src)
    block = img.apertures[10]
    assert isinstance(block, BlockAperture)
    assert len(block.draw_ops) == 2
    # Flash nets
    from gerberdelta.types import DrawOp
    assert all(isinstance(n, DrawOp) and n.aperture_state == ApertureState.Flash for n in block.draw_ops)


def test_block_aperture_nets_not_in_parent() -> None:
    """Nets inside a block do NOT appear in the parent ParsedImage.nets."""
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",
        "%AB*%",
    )
    img = parse_gerber(src)
    # Parent nets list should be empty (no drawing outside the block)
    assert len(img.draw_ops) == 0


def test_block_aperture_has_layers() -> None:
    """Parsed BlockAperture.layers is non-empty."""
    src = _gerber(
        "%ABD10*%",
        "%AB*%",
    )
    img = parse_gerber(src)
    block = img.apertures[10]
    assert isinstance(block, BlockAperture)
    assert len(block.layers) >= 1


def test_block_aperture_parent_apertures_accessible() -> None:
    """Apertures defined before the block are accessible inside it."""
    src = _gerber(
        "%ADD11C,0.05*%",  # defined before block
        "%ABD10*%",
        "D11*",  # use parent aperture inside block
        "X05000Y05000D03*",
        "%AB*%",
    )
    img = parse_gerber(src)
    block = img.apertures[10]
    assert isinstance(block, BlockAperture)
    # D11 should be in the block's apertures (copied from parent)
    assert 11 in block.apertures
    assert isinstance(block.apertures[11], CircleAperture)


def test_block_aperture_main_image_aperture_not_polluted() -> None:
    """Apertures defined INSIDE a block are NOT added to the parent dict."""
    src = _gerber(
        "%ABD10*%",
        "%ADD15C,0.2*%",  # defined INSIDE block
        "%AB*%",
    )
    img = parse_gerber(src)
    # D15 should NOT appear at the top-level (it was block-local)
    assert 15 not in img.apertures


def test_invalid_block_close_without_open_is_warning() -> None:
    """A stray %AB*% without an open produces a warning, not a crash."""
    src = _gerber("%AB*%")
    img = parse_gerber(src)
    msgs = [d.message for d in img.diagnostics]
    assert any("unexpected" in m.lower() for m in msgs)


def test_block_aperture_invalid_d_code_warning() -> None:
    """D-code below 10 in %ABD<n>*% produces a warning."""
    src = _gerber("%ABD05*%", "%AB*%")
    img = parse_gerber(src)
    msgs = [d.message for d in img.diagnostics]
    assert any("D-code" in m for m in msgs)


def test_block_flash_in_parent_compiles_to_block_flash() -> None:
    """Flashing a block aperture in the parent produces a BlockFlash group."""
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",
        "%AB*%",
        "D10*",
        "X50000Y50000D03*",  # flash block in parent
    )
    img = parse_gerber(src)
    assert len(img.draw_ops) == 1  # one flash in parent
    cr = compile_render(img)
    groups = [g for layer in cr.layers for g in layer.groups]
    block_flashes = [g for g in groups if isinstance(g, BlockFlash)]
    assert len(block_flashes) == 1
    assert block_flashes[0].aperture_code == 10


# ---------------------------------------------------------------------------
# Rendering tests
# ---------------------------------------------------------------------------


def test_block_flash_renders_without_crash() -> None:
    """Rendering a gerber with block apertures does not crash."""
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",
        "%AB*%",
        "D10*",
        "X50000Y50000D03*",
    )
    img = parse_gerber(src)
    vp = compute_viewport(img.bounding_box, 64, 64)
    arr = render_to_numpy(img, vp)
    assert arr.shape == (64, 64, 4)


def test_block_flash_produces_non_empty_render() -> None:
    """A board with only a block flash produces some non-transparent pixels."""
    src = _gerber(
        "%ADD11C,0.1*%",  # 0.1-inch circle
        "%ABD10*%",
        "D11*",
        "X00000Y00000D03*",
        "%AB*%",
        "D10*",
        "X00000Y00000D03*",
    )
    img = parse_gerber(src)
    vp = compute_viewport(img.bounding_box, 128, 128)
    arr = render_to_numpy(img, vp)
    # Some pixels should have non-zero alpha
    assert np.any(arr[..., 3] > 0)


def test_empty_block_flash_renders_cleanly() -> None:
    """An empty block aperture (no nets) flashed in the parent is a no-op."""
    src = _gerber(
        "%ABD10*%",
        "%AB*%",
        "D10*",
        "X00000Y00000D03*",
    )
    img = parse_gerber(src)
    vp = compute_viewport(img.bounding_box, 32, 32)
    arr = render_to_numpy(img, vp)
    # All transparent -- nothing was drawn
    assert np.all(arr[..., 3] == 0)


# ---------------------------------------------------------------------------
# Edge-case: empty gerber
# ---------------------------------------------------------------------------


def test_empty_gerber_no_crash() -> None:
    """Parsing and rendering an empty (geometry-less) gerber is safe."""
    src = "%FSLAX25Y25*%\n%MOIN*%\nM02*\n"
    img = parse_gerber(src)
    assert len(img.draw_ops) == 0
    assert not img.bounding_box.is_valid
    vp = compute_viewport(img.bounding_box, 128, 128)
    surface = render_to_surface(img, vp)
    assert surface is not None


def test_empty_gerber_viewport_is_default() -> None:
    """An invalid bounding box yields a centred default viewport."""
    bbox = BoundingBox()  # invalid (sentinel inf values)
    vp = compute_viewport(bbox, 256, 256)
    assert vp.width == 256
    assert vp.height == 256
    assert vp.zoom == 100.0


# ---------------------------------------------------------------------------
# Edge-case: negative-coordinate board
# ---------------------------------------------------------------------------


def test_negative_coordinate_viewport() -> None:
    """Boards with coordinates entirely in negative space render correctly."""
    bbox = BoundingBox(min_x=-3.0, min_y=-2.0, max_x=-1.0, max_y=-0.5)
    vp = compute_viewport(bbox, 256, 256)
    assert vp.zoom > 0
    # The board centre (-2, -1.25) must map to canvas centre (128, 128).
    # screen_x = pan_x + world_x * zoom -> 128 = pan_x + (-2)*zoom
    # screen_y = pan_y - world_y * zoom -> 128 = pan_y - (-1.25)*zoom
    center_x = (bbox.min_x + bbox.max_x) / 2.0
    center_y = (bbox.min_y + bbox.max_y) / 2.0
    screen_cx = vp.pan_x + center_x * vp.zoom
    screen_cy = vp.pan_y - center_y * vp.zoom
    assert abs(screen_cx - 128.0) < 1e-6
    assert abs(screen_cy - 128.0) < 1e-6


def test_negative_coordinate_render_non_empty() -> None:
    """A gerber with negative coordinates produces non-transparent pixels."""
    # Build a ParsedImage with a flash at (-1.0, -1.0)
    ap: dict[int, object] = {10: CircleAperture(diameter=0.1)}
    net = DrawOp(
        start_x=-1.0,
        start_y=-1.0,
        stop_x=-1.0,
        stop_y=-1.0,
        aperture_index=10,
        aperture_state=ApertureState.Flash,
        interpolation=__import__(
            "gerberdelta.types", fromlist=["InterpolationMode"]
        ).InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    bbox = BoundingBox()
    bbox.expand(-1.0, -1.0, 0.05)
    img = ParsedImage(
        draw_ops=[net],
        apertures=ap,  # type: ignore[arg-type]
        layers=[LayerState()],
        coord_states=[CoordState()],
        bounding_box=bbox,
        diagnostics=[],
    )
    vp = compute_viewport(img.bounding_box, 128, 128)
    arr = render_to_numpy(img, vp)
    assert np.any(arr[..., 3] > 0)


# ---------------------------------------------------------------------------
# Step-and-repeat rendering
# ---------------------------------------------------------------------------


def test_step_and_repeat_renders_multiple_copies() -> None:
    """SR 2x2 renders 4 copies of geometry, producing more lit pixels."""
    base_src = _gerber(
        "%ADD10C,0.1*%",
        "D10*",
        "X00000Y00000D03*",
        "M02*",
    )
    sr_src = (
        _HEADER
        + "%ADD10C,0.1*%\n"
        + "%SRX2Y2I1.0J1.0*%\n"
        + "D10*\n"
        + "X00000Y00000D03*\n"
        + "%SR*%\n"
        + "M02*\n"
    )

    img_base = parse_gerber(base_src)
    img_sr = parse_gerber(sr_src)

    merged_bbox = BoundingBox(min_x=0.0, min_y=0.0, max_x=1.1, max_y=1.1)
    vp = compute_viewport(merged_bbox, 256, 256)

    arr_base = render_to_numpy(img_base, vp)
    arr_sr = render_to_numpy(img_sr, vp)

    lit_base = int(np.sum(arr_base[..., 3] > 0))
    lit_sr = int(np.sum(arr_sr[..., 3] > 0))
    # SR 2x2 should produce more lit pixels than a single instance
    assert lit_sr > lit_base * 2
