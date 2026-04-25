from __future__ import annotations

import math

import pytest

from gerberdelta.types import (
    ApertureState,
    ApertureType,
    BoundingBox,
    CircleAperture,
    CoordState,
    DiffResult,
    DrawOp,
    InterpolationMode,
    LayerDiffResult,
    LayerState,
    LayerStatus,
    LayerType,
    MirrorState,
    ParsedImage,
    Polarity,
    Region,
    RegionFill,
    StepAndRepeat,
    UnitType,
)


def test_bounding_box_initial_state() -> None:
    bb = BoundingBox()
    assert bb.min_x == math.inf
    assert bb.min_y == math.inf
    assert bb.max_x == -math.inf
    assert bb.max_y == -math.inf
    assert not bb.is_valid


def test_bounding_box_expand() -> None:
    bb = BoundingBox()
    bb.expand(1.0, 2.0, radius=0.5)
    assert bb.is_valid
    assert bb.min_x == pytest.approx(0.5)
    assert bb.min_y == pytest.approx(1.5)
    assert bb.max_x == pytest.approx(1.5)
    assert bb.max_y == pytest.approx(2.5)

    # Expand again -- only extends outward
    bb.expand(0.0, 0.0)
    assert bb.min_x == pytest.approx(0.0)
    assert bb.min_y == pytest.approx(0.0)
    assert bb.max_x == pytest.approx(1.5)
    assert bb.max_y == pytest.approx(2.5)


def test_layer_state_defaults() -> None:
    ls = LayerState()
    assert ls.polarity is Polarity.Dark
    assert ls.rotation == pytest.approx(0.0)
    assert ls.mirror is MirrorState.None_
    assert ls.scale == pytest.approx(1.0)
    assert isinstance(ls.step_and_repeat, StepAndRepeat)
    assert ls.step_and_repeat.x == 1
    assert ls.step_and_repeat.y == 1
    assert ls.name is None


def test_net_state_defaults() -> None:
    ns = CoordState()
    assert ns.unit is UnitType.Inch


def test_parsed_image_empty() -> None:
    pi = ParsedImage(
        draw_ops=[],
        apertures={},
        layers=[],
        coord_states=[],
        bounding_box=BoundingBox(),
        diagnostics=[],
    )
    assert pi.source_path is None
    assert not pi.draw_ops
    assert not pi.apertures
    assert not pi.bounding_box.is_valid


def test_region_fill_construction() -> None:
    """RegionFill can be constructed and holds its segments."""
    seg = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=1.0,
        stop_y=0.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    rf = RegionFill(layer_index=0, net_state_index=0, segments=[seg])
    assert rf.layer_index == 0
    assert rf.net_state_index == 0
    assert len(rf.segments) == 1
    assert rf.segments[0] is seg


def test_region_bounding_box_field_name() -> None:
    """Field must be named bounding_box, not bbox (other phases depend on this)."""
    r = Region(
        id=1,
        centroid_x=0.5,
        centroid_y=0.5,
        bounding_box=BoundingBox(),
        pixel_count=100,
    )
    assert hasattr(r, "bounding_box")
    assert not hasattr(r, "bbox")


def test_diff_result_has_changes_property() -> None:
    """has_changes is a computed property: True when any layer has changes or
    non-Matched status; False when all layers are matched with zero changed pixels."""
    matched_clean = LayerDiffResult(
        name="F.Cu",
        status=LayerStatus.Matched,
        layer_type=LayerType.FCu,
        changed_pixel_count=0,
        total_pixel_count=1000,
        regions=[],
    )
    matched_dirty = LayerDiffResult(
        name="B.Cu",
        status=LayerStatus.Matched,
        layer_type=LayerType.BCu,
        changed_pixel_count=50,
        total_pixel_count=1000,
        regions=[],
    )
    added_layer = LayerDiffResult(
        name="In1.Cu",
        status=LayerStatus.Added,
        layer_type=LayerType.InCu,
        changed_pixel_count=0,
        total_pixel_count=1000,
        regions=[],
    )
    assert not DiffResult(layers=[matched_clean]).has_changes
    assert DiffResult(layers=[matched_dirty]).has_changes
    assert DiffResult(layers=[added_layer]).has_changes
    assert DiffResult(layers=[matched_clean, matched_dirty]).has_changes
    # Property is read-only
    dr = DiffResult(layers=[matched_clean])
    with pytest.raises(AttributeError):
        dr.has_changes = True  # type: ignore[misc]


def test_aperture_type_discriminator() -> None:
    """aperture_type field carries the correct Literal for each aperture class."""
    c = CircleAperture()
    assert c.aperture_type is ApertureType.Circle


def test_net_construction() -> None:
    net = DrawOp(
        start_x=0.0,
        start_y=0.0,
        stop_x=1.0,
        stop_y=1.0,
        aperture_index=10,
        aperture_state=ApertureState.On,
        interpolation=InterpolationMode.Linear,
        layer_index=0,
        net_state_index=0,
    )
    assert net.arc_segment is None
    assert net.attributes is None


def test_layer_diff_result_changed_fraction() -> None:
    layer = LayerDiffResult(
        name="B.Cu",
        status=LayerStatus.Matched,
        layer_type=LayerType.BCu,
        changed_pixel_count=250,
        total_pixel_count=1000,
        regions=[],
    )
    assert layer.changed_fraction == pytest.approx(0.25)


def test_layer_diff_result_changed_fraction_zero_denominator() -> None:
    layer = LayerDiffResult(
        name="B.Cu",
        status=LayerStatus.Added,
        layer_type=LayerType.BCu,
        changed_pixel_count=0,
        total_pixel_count=0,
        regions=[],
    )
    assert layer.changed_fraction == pytest.approx(0.0)
