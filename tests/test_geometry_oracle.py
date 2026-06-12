"""Integration tests: geometry diff vs the investigated ground truth.

The expected numbers were established by nearest-neighbour matching of
before->after flash centroids on the A64-OlinuXino fixture pair (see
``docs/geometry-diff.md``).  For ``F.Paste``:

- 1211 unchanged flashes (engine adds a few unchanged strokes/regions),
- 46 paired within 0.2 mm: the engine splits these into ``moved`` (same
  dims) and ``resized`` (footprint replaced) -- together they must equal 46,
- 81 before-flashes with no counterpart -> ``removed``.

These bounds pin the attribution pipeline end-to-end on real boards.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import pytest

from gerberdiff.geometry import compute_geometry_diff

_FIXTURES = Path(__file__).parent / "fixtures"
_BEFORE = _FIXTURES / "gerbers-before"
_AFTER = _FIXTURES / "gerbers-after"

pytestmark = pytest.mark.skipif(
    not (_BEFORE.exists() and _AFTER.exists()),
    reason="fixture boards not present",
)


def test_fpaste_matches_oracle() -> None:
    result = compute_geometry_diff(_BEFORE, _AFTER, layers=["A64-OlinuXino-F.Paste"])
    layer = result.layers[0]

    moved = layer.count("moved")
    resized = layer.count("resized")
    removed = layer.count("removed")
    added = layer.count("added")

    # Oracle: 46 same-object pairs, 81 removed, 160 added flashes.
    assert moved + resized == 46
    assert removed == 81
    assert added == 160
    # 1211 unchanged flashes; strokes/regions add a small remainder.
    assert 1211 <= layer.unchanged_count <= 1220

    # Mean displacement of all paired changes ~ (-0.139, -0.054) mm.
    paired = [c for c in layer.changes if c.kind in ("moved", "resized")]
    mean_dx = sum(c.dx_mm or 0.0 for c in paired) / len(paired)
    mean_dy = sum(c.dy_mm or 0.0 for c in paired) / len(paired)
    assert math.isclose(mean_dx, -0.139, abs_tol=0.005)
    assert math.isclose(mean_dy, -0.054, abs_tol=0.005)


def test_identical_directories_no_changes() -> None:
    result = compute_geometry_diff(_BEFORE, _BEFORE)
    assert not result.has_changes
    for layer in result.layers:
        assert layer.changes == []
        assert layer.added_area_mm2 == 0.0
        assert layer.removed_area_mm2 == 0.0


def test_edge_cuts_layer_unchanged_between_revisions() -> None:
    """Edge.Cuts is identical in both revisions (raster diff: 0 changed px)."""
    result = compute_geometry_diff(_BEFORE, _AFTER, layers=["A64-OlinuXino-Edge.Cuts"])
    layer = result.layers[0]
    assert layer.changes == []
    assert layer.added_area_mm2 == 0.0
    assert layer.removed_area_mm2 == 0.0
    assert layer.unchanged_count > 0  # outline strokes all matched exactly


def test_drill_layers_diff() -> None:
    """Excellon drill layers run through the same pipeline."""
    result = compute_geometry_diff(_BEFORE, _AFTER, layers=["A64-OlinuXino-PTH"])
    layer = result.layers[0]
    # The PTH drill pattern changed between revisions.
    assert layer.has_changes
    assert layer.unchanged_count > 0


def test_full_board_within_time_budget() -> None:
    """All 15 layers must geometry-diff comfortably faster than the raster
    engine (16 s on this board).  Generous CI headroom on the threshold."""
    t0 = time.perf_counter()
    result = compute_geometry_diff(_BEFORE, _AFTER)
    elapsed = time.perf_counter() - t0
    assert len(result.layers) == 15
    assert result.has_changes
    assert elapsed < 60.0, f"geometry diff took {elapsed:.1f}s"


def test_added_layer_reports_total_area(tmp_path: Path) -> None:
    """A layer present only in after/ reports status=added with its area."""
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    src = (_AFTER / "A64-OlinuXino-F.Paste.gbr").read_text()
    (after / "new-F.Paste.gbr").write_text(src)
    result = compute_geometry_diff(before, after)
    layer = result.layers[0]
    assert layer.status.value == "added"
    assert layer.added_area_mm2 > 0.0
    assert layer.removed_area_mm2 == 0.0
    assert result.has_changes
