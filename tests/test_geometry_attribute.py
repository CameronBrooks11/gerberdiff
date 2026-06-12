"""Tests for geometry/attribute.py: matching and change classification."""

from __future__ import annotations

import math

from gerberdiff.geometry.attribute import attribute_changes, partition_unchanged
from gerberdiff.geometry.layer_geometry import LayerGeometry, build_layer_geometry
from gerberdiff.parse.gerber_state import parse_gerber

_HEADER = "%FSLAX26Y26*%\n%MOIN*%\n"
_FOOTER = "M02*\n"

# Engine-internal units are inches.
_MOVE_TOL = 0.005 / 25.4
_GATE = 0.2 / 25.4
_AREA_TOL = 0.01


def _gerber(*body_lines: str) -> str:
    return _HEADER + "\n".join(body_lines) + "\n" + _FOOTER


def _build(*body_lines: str) -> LayerGeometry:
    return build_layer_geometry(parse_gerber(_gerber(*body_lines)))


def _classify(a: LayerGeometry, b: LayerGeometry) -> tuple[dict[str, int], int]:
    parts = partition_unchanged(a.ops, b.ops)
    changes, unchanged = attribute_changes(
        parts, move_tol=_MOVE_TOL, gate_radius=_GATE, area_tol=_AREA_TOL
    )
    counts: dict[str, int] = {"added": 0, "removed": 0, "moved": 0, "resized": 0}
    for c in changes:
        counts[c.kind] += 1
    return counts, unchanged


# ---------------------------------------------------------------------------
# Exact cancellation
# ---------------------------------------------------------------------------


def test_identical_all_unchanged() -> None:
    lines = ("%ADD10C,0.1*%", "D10*", "X0Y0D03*", "X1000000Y0D03*")
    counts, unchanged = _classify(_build(*lines), _build(*lines))
    assert counts == {"added": 0, "removed": 0, "moved": 0, "resized": 0}
    assert unchanged == 2


def test_duplicate_ops_multiset_matched() -> None:
    """Two identical flashes at the same spot in A, one in B: one removed."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    counts, unchanged = _classify(a, b)
    assert unchanged == 1
    assert counts["removed"] == 1


# ---------------------------------------------------------------------------
# Moved
# ---------------------------------------------------------------------------


def test_moved_pad() -> None:
    """0.1 mm shift (X+0.1mm = 3937 units at 1e-6 in resolution)."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X3937Y0D03*")
    parts = partition_unchanged(a.ops, b.ops)
    changes, unchanged = attribute_changes(
        parts, move_tol=_MOVE_TOL, gate_radius=_GATE, area_tol=_AREA_TOL
    )
    assert unchanged == 0
    assert len(changes) == 1
    change = changes[0]
    assert change.kind == "moved"
    assert math.isclose(change.dx * 25.4, 0.1, rel_tol=1e-3)
    assert math.isclose(change.dy, 0.0, abs_tol=1e-12)


def test_sub_tolerance_move_is_unchanged() -> None:
    """A 2 um nudge is below the 5 um move tolerance."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X79Y0D03*")  # 79e-6 in ~ 2 um
    counts, unchanged = _classify(a, b)
    assert counts == {"added": 0, "removed": 0, "moved": 0, "resized": 0}
    assert unchanged == 1


def test_rotated_rect_pad_is_moved_not_resized() -> None:
    """W/H swap (90-degree footprint rotation) keeps dims -> moved."""
    a = _build("%ADD10R,0.06X0.03*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10R,0.03X0.06*%", "D10*", "X3937Y0D03*")
    counts, _ = _classify(a, b)
    assert counts["moved"] == 1
    assert counts["resized"] == 0


# ---------------------------------------------------------------------------
# Resized
# ---------------------------------------------------------------------------


def test_resized_pad_same_position() -> None:
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.08*%", "D10*", "X0Y0D03*")
    counts, unchanged = _classify(a, b)
    assert counts["resized"] == 1
    assert unchanged == 0


def test_replaced_pad_nearby_is_resized() -> None:
    """Different aperture within the gate radius pairs as resized."""
    a = _build("%ADD10R,0.05X0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10R,0.08X0.02*%", "D10*", "X2000Y2000D03*")
    counts, _ = _classify(a, b)
    assert counts["resized"] == 1
    assert counts["added"] == 0
    assert counts["removed"] == 0


# ---------------------------------------------------------------------------
# Added / removed and gating
# ---------------------------------------------------------------------------


def test_far_move_beyond_gate_is_add_remove() -> None:
    """A pad displaced beyond the gate radius cannot pair."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "X500000Y0D03*")  # 0.5 in >> gate
    counts, _ = _classify(a, b)
    assert counts["added"] == 1
    assert counts["removed"] == 1
    assert counts["moved"] == 0


def test_kind_pools_flash_never_matches_stroke() -> None:
    """A flash replaced by an equal-area stroke nearby: add + remove."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD11C,0.05*%", "D11*", "X0Y0D02*", "X2000Y0D01*")
    counts, _ = _classify(a, b)
    assert counts["added"] == 1
    assert counts["removed"] == 1
    assert counts["moved"] == 0
    assert counts["resized"] == 0


def test_polarity_pools_dark_never_matches_clear() -> None:
    """A dark pad in A and a clear pad in B at the same spot do not pair."""
    a = _build("%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "%LPC*%", "D10*", "X0Y0D03*")
    counts, _ = _classify(a, b)
    assert counts["added"] == 1
    assert counts["removed"] == 1


def test_dense_array_pairs_correctly() -> None:
    """A 3x3 grid shifted uniformly must pair one-to-one (no cross-pairing).

    Grid pitch 0.04 in ~ 1 mm; shift 0.1 mm; gate 0.2 mm < pitch."""
    pitch = 40000  # 0.04 in, in 1e-6 units
    shift = 3937  # 0.1 mm
    pads_a = [f"X{ix * pitch}Y{iy * pitch}D03*" for ix in range(3) for iy in range(3)]
    pads_b = [f"X{ix * pitch + shift}Y{iy * pitch}D03*" for ix in range(3) for iy in range(3)]
    a = _build("%ADD10C,0.02*%", "D10*", *pads_a)
    b = _build("%ADD10C,0.02*%", "D10*", *pads_b)
    parts = partition_unchanged(a.ops, b.ops)
    changes, unchanged = attribute_changes(
        parts, move_tol=_MOVE_TOL, gate_radius=_GATE, area_tol=_AREA_TOL
    )
    assert unchanged == 0
    assert len(changes) == 9
    assert all(c.kind == "moved" for c in changes)
    for c in changes:
        assert math.isclose(c.dx * 25.4, 0.1, rel_tol=1e-3)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_net_name_carried_into_changes() -> None:
    a = _build("%ADD10C,0.1*%", "D10*", "%TO.N,GND*%", "X0Y0D03*")
    b = _build("%ADD10C,0.1*%", "D10*", "%TO.N,GND*%", "X3937Y0D03*")
    parts = partition_unchanged(a.ops, b.ops)
    changes, _ = attribute_changes(parts, move_tol=_MOVE_TOL, gate_radius=_GATE, area_tol=_AREA_TOL)
    assert changes[0].after is not None
    assert changes[0].after.net_name == "GND"
