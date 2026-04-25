from __future__ import annotations

from gerberdelta.render.viewport import (
    compute_viewport,
    merge_bounding_boxes,
    screen_to_world,
)
from gerberdelta.types import BoundingBox


def _bbox(*points: tuple[float, float]) -> BoundingBox:
    bb = BoundingBox()
    for x, y in points:
        bb.expand(x, y)
    return bb


def test_compute_viewport_basic() -> None:
    bb = _bbox((0.0, 0.0), (1.0, 1.0))
    vp = compute_viewport(bb, 1000, 1000)
    assert vp.zoom > 0
    # World (0.5, 0.5) should map close to canvas centre (500, 500)
    sx = vp.pan_x + 0.5 * vp.zoom
    sy = vp.pan_y - 0.5 * vp.zoom
    assert abs(sx - 500) < 10
    assert abs(sy - 500) < 10


def test_compute_viewport_margin() -> None:
    bb = _bbox((0.0, 0.0), (1.0, 1.0))
    vp = compute_viewport(bb, 1000, 1000)
    # 10% margin → zoom should be 0.9 * (canvas / board_size)
    expected_zoom = 0.9 * 1000.0
    assert abs(vp.zoom - expected_zoom) < 1e-6


def test_compute_viewport_invalid_bbox() -> None:
    bb = BoundingBox()  # invalid — no points added
    vp = compute_viewport(bb, 800, 600)
    assert vp.zoom == 100.0  # default fallback


def test_compute_viewport_non_square_canvas() -> None:
    bb = _bbox((0.0, 0.0), (2.0, 1.0))  # 2:1 board on 1000x1000 canvas
    vp = compute_viewport(bb, 1000, 1000)
    # Limiting axis is width: zoom = 0.9 * (1000/2) = 450
    assert abs(vp.zoom - 450.0) < 1e-6


def test_screen_to_world_roundtrip() -> None:
    bb = _bbox((0.0, 0.0), (2.0, 2.0))
    vp = compute_viewport(bb, 2048, 2048)
    world_x, world_y = 1.0, 1.0
    px = vp.pan_x + world_x * vp.zoom
    py = vp.pan_y - world_y * vp.zoom
    rx, ry = screen_to_world(px, py, vp)
    assert abs(rx - world_x) < 1e-9
    assert abs(ry - world_y) < 1e-9


def test_screen_to_world_y_flip() -> None:
    bb = _bbox((0.0, 0.0), (1.0, 1.0))
    vp = compute_viewport(bb, 500, 500)
    # Moving pixel down (larger py) should decrease world_y
    _, y0 = screen_to_world(250.0, 250.0, vp)
    _, y1 = screen_to_world(250.0, 260.0, vp)
    assert y1 < y0


def test_merge_bounding_boxes() -> None:
    a = _bbox((0.0, 0.0), (1.0, 1.0))
    b = _bbox((2.0, 2.0), (3.0, 3.0))
    m = merge_bounding_boxes(a, b)
    assert m.min_x == 0.0
    assert m.min_y == 0.0
    assert m.max_x == 3.0
    assert m.max_y == 3.0


def test_merge_with_invalid_b() -> None:
    a = _bbox((0.0, 0.0), (1.0, 1.0))
    b = BoundingBox()  # invalid
    m = merge_bounding_boxes(a, b)
    assert m.is_valid
    assert m.min_x == 0.0
    assert m.max_x == 1.0


def test_merge_both_invalid() -> None:
    a = BoundingBox()
    b = BoundingBox()
    m = merge_bounding_boxes(a, b)
    assert not m.is_valid
