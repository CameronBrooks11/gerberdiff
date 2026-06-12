"""Tests for geometry/geom_diff.py: boolean added/removed material."""

from __future__ import annotations

import math

from gerberdiff.geometry.attribute import partition_unchanged
from gerberdiff.geometry.geom_diff import boolean_layer_diff
from gerberdiff.geometry.layer_geometry import LayerGeometry, build_layer_geometry
from gerberdiff.parse.gerber_state import parse_gerber

_HEADER = "%FSLAX25Y25*%\n%MOIN*%\n"
_FOOTER = "M02*\n"


def _gerber(*body_lines: str) -> str:
    return _HEADER + "\n".join(body_lines) + "\n" + _FOOTER


def _build(*body_lines: str) -> LayerGeometry:
    return build_layer_geometry(parse_gerber(_gerber(*body_lines)))


def _diff(a: LayerGeometry, b: LayerGeometry, dust_area: float = 0.0) -> tuple[float, float]:
    """Run partition + boolean diff; return (added, removed) areas in in^2."""
    parts = partition_unchanged(a.ops, b.ops)
    added, removed = boolean_layer_diff(
        a, b, parts.a_only, parts.b_only, parts.unchanged_a, dust_area=dust_area
    )
    return added.area, removed.area


# ---------------------------------------------------------------------------
# Fast path (all dark)
# ---------------------------------------------------------------------------


def test_identical_layers_empty_diff() -> None:
    lines = ("%ADD10C,0.1*%", "D10*", "X0Y0D03*", "X100000Y0D03*")
    added, removed = _diff(_build(*lines), _build(*lines))
    assert added == 0.0
    assert removed == 0.0


def test_added_pad() -> None:
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*", "X100000Y0D03*")
    added, removed = _diff(a, b)
    assert math.isclose(added, math.pi * 0.05**2, rel_tol=5e-3)
    assert removed == 0.0


def test_removed_pad() -> None:
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*", "X100000Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    added, removed = _diff(a, b)
    assert added == 0.0
    assert math.isclose(removed, math.pi * 0.05**2, rel_tol=5e-3)


def test_moved_rect_pad_crescents() -> None:
    """1.0 x 0.5 rect moved +0.2 in X: added = removed = 0.2 * 0.5 exactly."""
    a = _build("%ADD10R,1.0X0.5*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10R,1.0X0.5*%", "D10*", "X20000Y0D03*")
    added, removed = _diff(a, b)
    assert math.isclose(added, 0.2 * 0.5, rel_tol=1e-9)
    assert math.isclose(removed, 0.2 * 0.5, rel_tol=1e-9)


def test_unchanged_context_masks_difference() -> None:
    """A removed trace under an unchanged pad: only the uncovered part of
    the trace counts as removed.  This is the exactness test for the
    interacting-context fast path."""
    pad = ("%ADD10C,0.2*%", "D10*", "X0Y0D03*")
    trace = ("%ADD11C,0.05*%", "D11*", "X0Y0D02*", "X50000Y0D01*")
    a = _build(*pad, *trace)
    b = _build(*pad)
    added, removed = _diff(a, b)
    assert added == 0.0
    # Removed = capsule minus the part covered by the unchanged 0.2-dia pad.
    capsule = 0.5 * 0.05 + math.pi * 0.025**2
    # The pad covers the capsule for x in [0, ~0.1] including the start cap.
    covered = 0.1 * 0.05 + math.pi * 0.025**2 / 2.0
    assert math.isclose(removed, capsule - covered, rel_tol=0.02)


def test_no_changes_no_geometry_work() -> None:
    """Empty a_only/b_only short-circuits to empty results."""
    lines = ("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    a, b = _build(*lines), _build(*lines)
    parts = partition_unchanged(a.ops, b.ops)
    assert not parts.a_only and not parts.b_only
    added, removed = boolean_layer_diff(a, b, [], [], parts.unchanged_a)
    assert added.is_empty and removed.is_empty


def test_dust_filter_drops_small_components() -> None:
    """A pad shrunk by a hair produces a thin ring below the dust floor."""
    a = _build("%ADD10C,0.100000*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.100002*%", "D10*", "X0Y0D03*")
    added_raw, _ = _diff(a, b, dust_area=0.0)
    added_dusted, _ = _diff(a, b, dust_area=1e-6)
    assert added_raw > 0.0
    assert added_dusted == 0.0


# ---------------------------------------------------------------------------
# Full path (clear polarity present)
# ---------------------------------------------------------------------------


def _pour_with_cutout(cut_x: int) -> LayerGeometry:
    return _build(
        "%ADD10C,0.2*%",
        "G36*",
        "X0Y0D02*",
        "X100000Y0D01*",
        "X100000Y100000D01*",
        "X0Y100000D01*",
        "X0Y0D01*",
        "G37*",
        "%LPC*%",
        "D10*",
        f"X{cut_x}Y50000D03*",
    )


def test_clear_layer_uses_full_path_identical() -> None:
    a = _pour_with_cutout(50000)
    b = _pour_with_cutout(50000)
    assert a.has_clear
    added, removed = _diff(a, b)
    assert added == 0.0
    assert removed == 0.0


def test_moved_clear_cutout() -> None:
    """Moving a cutout inside a pour: added material where the old hole was,
    removed material where the new hole is."""
    a = _pour_with_cutout(30000)
    b = _pour_with_cutout(70000)
    added, removed = _diff(a, b)
    disc = math.pi * 0.1**2
    assert math.isclose(added, disc, rel_tol=5e-3)
    assert math.isclose(removed, disc, rel_tol=5e-3)


def test_clear_on_one_side_only_still_full_path() -> None:
    a = _build("%ADD10C,0.2*%", "D10*", "X50000Y50000D03*")
    b = _pour_with_cutout(50000)
    added, removed = _diff(a, b)
    pour = 1.0
    disc = math.pi * 0.1**2
    assert math.isclose(added, pour - disc, rel_tol=5e-3)
    assert math.isclose(removed, disc, rel_tol=5e-3)  # the dark pad got cleared
