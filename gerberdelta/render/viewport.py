from __future__ import annotations

from dataclasses import dataclass

from gerberdelta.types import BoundingBox


@dataclass
class Viewport:
    """Canvas viewport parameters derived from a board's bounding box.

    Coordinate convention:
        screen_x = pan_x + world_x * zoom
        screen_y = pan_y - world_y * zoom   (Y-flipped: Gerber +Y is screen up)
    """

    width: int
    height: int
    pan_x: float   # canvas X of the world origin
    pan_y: float   # canvas Y of the world origin (after Y-flip)
    zoom: float    # world units → pixels


def compute_viewport(bbox: BoundingBox, width: int, height: int) -> Viewport:
    """Fit *bbox* into a *width* x *height* canvas with a 10% margin.

    Returns a default viewport (zoom=100, centred) when the bbox is invalid
    or has zero extent in either axis.
    """
    if not bbox.is_valid:
        return Viewport(
            width=width, height=height,
            pan_x=width / 2.0, pan_y=height / 2.0,
            zoom=100.0,
        )

    bbox_w = bbox.max_x - bbox.min_x
    bbox_h = bbox.max_y - bbox.min_y

    if bbox_w <= 0.0 or bbox_h <= 0.0:
        return Viewport(
            width=width, height=height,
            pan_x=width / 2.0, pan_y=height / 2.0,
            zoom=100.0,
        )

    zoom = min(width / bbox_w, height / bbox_h) * 0.9
    center_x = bbox.min_x + bbox_w / 2.0
    center_y = bbox.min_y + bbox_h / 2.0
    pan_x = width / 2.0 - center_x * zoom
    pan_y = height / 2.0 + center_y * zoom  # Y-flip

    return Viewport(width=width, height=height, pan_x=pan_x, pan_y=pan_y, zoom=zoom)


def merge_bounding_boxes(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    """Return the axis-aligned union of two BoundingBoxes.

    If one box is invalid (empty) the other is returned unchanged.
    If both are invalid the result is also invalid.
    """
    result = BoundingBox()
    if a.is_valid:
        result.expand(a.min_x, a.min_y)
        result.expand(a.max_x, a.max_y)
    if b.is_valid:
        result.expand(b.min_x, b.min_y)
        result.expand(b.max_x, b.max_y)
    return result


def screen_to_world(px: float, py: float, vp: Viewport) -> tuple[float, float]:
    """Convert pixel coordinates back to world (inch) coordinates.

    Inverts the transform:
        screen_x = pan_x + world_x * zoom
        screen_y = pan_y - world_y * zoom
    """
    world_x = (px - vp.pan_x) / vp.zoom
    world_y = -(py - vp.pan_y) / vp.zoom
    return world_x, world_y
