"""Tests for diff/diff_engine.py."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gerberdiff.diff.diff_engine import (
    SingleLayerDiff,
    _merge_region_pair,
    boxes_overlap,
    compute_diff,
    merge_overlapping_regions,
)
from gerberdiff.parse.gerber_state import parse_gerber
from gerberdiff.types import BoundingBox, LayerState, ParsedImage, Region

_FIXTURES_BEFORE = Path(__file__).parent / "fixtures" / "gerbers-before"
_FIXTURES_AFTER = Path(__file__).parent / "fixtures" / "gerbers-after"
_FCU_BEFORE = _FIXTURES_BEFORE / "A64-OlinuXino-F.Cu.gbr"
_FCU_AFTER = _FIXTURES_AFTER / "A64-OlinuXino-F.Cu.gbr"


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


def _bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> BoundingBox:
    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _region(
    rid: int,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    px: int = 100,
) -> Region:
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    return Region(
        id=rid,
        centroid_x=cx,
        centroid_y=cy,
        bounding_box=_bbox(min_x, min_y, max_x, max_y),
        pixel_count=px,
    )


# ---------------------------------------------------------------------------
# boxes_overlap
# ---------------------------------------------------------------------------


def test_boxes_overlap_identical() -> None:
    bb = _bbox(0.0, 0.0, 1.0, 1.0)
    assert boxes_overlap(bb, bb, 0.0)


def test_boxes_overlap_adjacent_no_tolerance() -> None:
    a = _bbox(0.0, 0.0, 1.0, 1.0)
    b = _bbox(1.0, 0.0, 2.0, 1.0)
    # Exactly touching: max_x(a) == min_x(b) -> not strictly separated
    assert boxes_overlap(a, b, 0.0)


def test_boxes_overlap_separated_no_tolerance() -> None:
    a = _bbox(0.0, 0.0, 1.0, 1.0)
    b = _bbox(2.0, 0.0, 3.0, 1.0)
    assert not boxes_overlap(a, b, 0.0)


def test_boxes_overlap_separated_with_tolerance() -> None:
    a = _bbox(0.0, 0.0, 1.0, 1.0)
    b = _bbox(1.5, 0.0, 2.5, 1.0)
    # Gap = 0.5; tolerance pads each box outward, effective gap = 0.5 - 2*tol.
    # tolerance 0.2 -> effective gap 0.1 -> no overlap
    assert not boxes_overlap(a, b, 0.2)
    # tolerance 0.3 -> effective gap -0.1 -> overlap
    assert boxes_overlap(a, b, 0.3)


def test_boxes_no_overlap_y_axis() -> None:
    a = _bbox(0.0, 0.0, 1.0, 1.0)
    b = _bbox(0.0, 3.0, 1.0, 4.0)
    assert not boxes_overlap(a, b, 0.0)
    assert not boxes_overlap(a, b, 0.9)


# ---------------------------------------------------------------------------
# _merge_region_pair
# ---------------------------------------------------------------------------


def test_merge_region_pair_weighted_centroid() -> None:
    a = Region(
        id=1,
        centroid_x=0.0,
        centroid_y=0.0,
        bounding_box=_bbox(0.0, 0.0, 1.0, 1.0),
        pixel_count=100,
    )
    b = Region(
        id=2,
        centroid_x=2.0,
        centroid_y=2.0,
        bounding_box=_bbox(1.5, 1.5, 2.5, 2.5),
        pixel_count=100,
    )
    m = _merge_region_pair(a, b)
    assert m.centroid_x == pytest.approx(1.0)
    assert m.centroid_y == pytest.approx(1.0)
    assert m.pixel_count == 200
    assert m.bounding_box.min_x == pytest.approx(0.0)
    assert m.bounding_box.max_x == pytest.approx(2.5)
    assert m.id == 1  # keeps id of first


def test_merge_region_pair_unequal_weights() -> None:
    a = Region(
        id=1,
        centroid_x=0.0,
        centroid_y=0.0,
        bounding_box=_bbox(0.0, 0.0, 0.1, 0.1),
        pixel_count=300,
    )
    b = Region(
        id=2,
        centroid_x=6.0,
        centroid_y=0.0,
        bounding_box=_bbox(5.9, 0.0, 6.1, 0.1),
        pixel_count=100,
    )
    m = _merge_region_pair(a, b)
    assert m.centroid_x == pytest.approx(1.5)  # (0*300 + 6*100) / 400


# ---------------------------------------------------------------------------
# merge_overlapping_regions
# ---------------------------------------------------------------------------


def test_merge_overlapping_regions_empty() -> None:
    assert merge_overlapping_regions([]) == []


def test_merge_overlapping_regions_single() -> None:
    r = _region(1, 0.0, 0.0, 1.0, 1.0)
    result = merge_overlapping_regions([r])
    assert len(result) == 1


def test_merge_overlapping_regions_touching_boxes_merge() -> None:
    a = _region(1, 0.0, 0.0, 1.0, 1.0, px=50)
    b = _region(2, 0.9, 0.0, 1.9, 1.0, px=50)
    result = merge_overlapping_regions([a, b], tolerance=0.0)
    assert len(result) == 1
    assert result[0].pixel_count == 100


def test_merge_overlapping_regions_distant_no_merge() -> None:
    a = _region(1, 0.0, 0.0, 1.0, 1.0)
    b = _region(2, 5.0, 5.0, 6.0, 6.0)
    result = merge_overlapping_regions([a, b], tolerance=0.0)
    assert len(result) == 2


def test_merge_overlapping_regions_sort_order() -> None:
    """After merging, regions sorted by descending centroid_y, then asc centroid_x."""
    regions = [
        _region(1, 0.0, 0.0, 0.1, 0.1),  # centroid_y ~= 0.05
        _region(2, 0.0, 5.0, 0.1, 5.1),  # centroid_y ~= 5.05  (highest)
        _region(3, 0.0, 2.0, 0.1, 2.1),  # centroid_y ~= 2.05
    ]
    result = merge_overlapping_regions(regions, tolerance=0.0)
    assert len(result) == 3
    assert result[0].id == 1  # was region 2 after sort (highest y)
    assert result[0].centroid_y == pytest.approx(5.05, abs=0.01)
    assert result[1].centroid_y == pytest.approx(2.05, abs=0.01)
    assert result[2].centroid_y == pytest.approx(0.05, abs=0.01)


def test_merge_overlapping_regions_ids_renumbered() -> None:
    regions = [_region(10, i * 10.0, 0.0, i * 10.0 + 1.0, 1.0) for i in range(4)]
    result = merge_overlapping_regions(regions, tolerance=0.0)
    assert [r.id for r in result] == list(range(1, len(result) + 1))


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


def test_compute_diff_empty_images_no_changes() -> None:
    a = _empty_image()
    b = _empty_image()
    result = compute_diff(a, b, width=64, height=64)
    assert isinstance(result, SingleLayerDiff)
    assert result.changed_pixel_count == 0
    assert result.total_pixel_count == 64 * 64
    assert result.regions == []


@pytest.mark.skipif(
    not (_FCU_BEFORE.exists() and _FCU_AFTER.exists()),
    reason="fixtures not found",
)
def test_compute_diff_before_after_has_changes() -> None:
    """Diffing before vs after F.Cu finds non-zero changed regions."""
    img_a = parse_gerber(_FCU_BEFORE.read_text(encoding="utf-8"), source_path=_FCU_BEFORE)
    img_b = parse_gerber(_FCU_AFTER.read_text(encoding="utf-8"), source_path=_FCU_AFTER)
    result = compute_diff(img_a, img_b, width=512, height=512)
    assert result.changed_pixel_count > 0
    assert len(result.regions) > 0


@pytest.mark.skipif(not _FCU_BEFORE.exists(), reason="fixture not found")
def test_compute_diff_identical_no_changes() -> None:
    """Diffing a file against itself produces zero changed pixels."""
    img = parse_gerber(_FCU_BEFORE.read_text(encoding="utf-8"), source_path=_FCU_BEFORE)
    result = compute_diff(img, img, width=256, height=256)
    assert result.changed_pixel_count == 0
    assert result.regions == []


@pytest.mark.skipif(not _FCU_BEFORE.exists(), reason="fixture not found")
def test_compute_diff_overlay_callback_called() -> None:
    """overlay_callback receives (arr_a, arr_b, xor) each shape (H,W,4) uint8."""
    img = parse_gerber(_FCU_BEFORE.read_text(encoding="utf-8"), source_path=_FCU_BEFORE)

    captured: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    def _cb(a: np.ndarray, b: np.ndarray, x: np.ndarray) -> None:
        captured.append((a, b, x))

    result = compute_diff(img, img, width=128, height=128, overlay_callback=_cb)
    assert len(captured) == 1
    a, b, x = captured[0]
    assert a.shape == (128, 128, 4)
    assert b.shape == (128, 128, 4)
    assert x.shape == (128, 128, 4)
    assert a.dtype == np.uint8
    assert result.changed_pixel_count == 0  # identical images


@pytest.mark.skipif(not _FCU_BEFORE.exists(), reason="fixture not found")
def test_compute_diff_no_callback_no_error() -> None:
    """overlay_callback=None (default) must not raise."""
    img = parse_gerber(_FCU_BEFORE.read_text(encoding="utf-8"), source_path=_FCU_BEFORE)
    result = compute_diff(img, img, width=64, height=64)
    assert result.changed_pixel_count == 0


# ---------------------------------------------------------------------------
# P7-5: merge_overlapping_regions cascade
# ---------------------------------------------------------------------------


def test_merge_cascade_three_regions() -> None:
    """A-C overlap, C-B overlap, but A-B do NOT overlap directly.

    After merging A+C → A', A' now overlaps B → all three merge into one.
    """
    # A=[0,0,2,1], C=[1.5,0,3,1], B=[2.5,0,4,1]; tolerance=0.1
    # A ends at x=2, C starts at x=1.5 → overlap (2 > 1.5)
    # C ends at x=3, B starts at x=2.5 → overlap (3 > 2.5)
    # A ends at x=2, B starts at x=2.5 → gap=0.5 > tolerance → no direct A-B overlap
    r_a = _region(1, 0.0, 0.0, 2.0, 1.0)
    r_c = _region(2, 1.5, 0.0, 3.0, 1.0)
    r_b = _region(3, 2.5, 0.0, 4.0, 1.0)
    result = merge_overlapping_regions([r_a, r_c, r_b], tolerance=0.1)
    assert len(result) == 1, f"Expected all three to cascade-merge into 1 region, got {len(result)}"
    merged = result[0]
    assert merged.bounding_box.min_x <= 0.0
    assert merged.bounding_box.max_x >= 4.0


# ---------------------------------------------------------------------------
# P7-9: compute_diff alignment_offset
# ---------------------------------------------------------------------------


def _dot_image(x: float = 0.0, y: float = 0.0) -> ParsedImage:
    """ParsedImage with a single circle flash at (x, y)."""
    ap_code = 10
    from gerberdiff.types import ApertureState, DrawOp, InterpolationMode

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
    from gerberdiff.types import CircleAperture

    bb = BoundingBox()
    bb.expand(x, y, 0.02)
    return ParsedImage(
        draw_ops=[net],
        apertures={ap_code: CircleAperture(diameter=0.04)},
        layers=[LayerState()],
        coord_states=[],
        bounding_box=bb,
        diagnostics=[],
    )


def test_compute_diff_alignment_offset_shifts_b() -> None:
    """A large alignment_offset moves image_b out of alignment → changed pixels > 0."""
    img = _dot_image(0.0, 0.0)
    # Without offset: identical images → zero changed pixels.
    result_no_offset = compute_diff(img, img, width=64, height=64)
    assert result_no_offset.changed_pixel_count == 0

    # With a 1-inch offset image_b is shifted far off the viewport → many changed pixels.
    result_offset = compute_diff(img, img, width=64, height=64, alignment_offset=(1.0, 0.0))
    assert result_offset.changed_pixel_count > 0, (
        "alignment_offset=(1.0, 0.0) should shift image_b so there are changed pixels"
    )
