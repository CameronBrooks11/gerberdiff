"""Tests for diff/layer_matcher.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from gerberdiff.diff.layer_matcher import (
    classify_layer,
    match_layers,
)
from gerberdiff.types import LayerStatus, LayerType

_FIXTURES_BEFORE = Path(__file__).parent / "fixtures" / "gerbers-before"
_FIXTURES_AFTER = Path(__file__).parent / "fixtures" / "gerbers-after"


# ---------------------------------------------------------------------------
# classify_layer
# ---------------------------------------------------------------------------


def _fake(stem: str, suffix: str = ".gbr") -> Path:
    return Path(f"board-{stem}{suffix}")


def test_classify_fcu() -> None:
    assert classify_layer(_fake("F.Cu")) == LayerType.FCu


def test_classify_bcu() -> None:
    assert classify_layer(_fake("B.Cu")) == LayerType.BCu


def test_classify_incu() -> None:
    assert classify_layer(_fake("In2.Cu")) == LayerType.InCu


def test_classify_fmask() -> None:
    assert classify_layer(_fake("F.Mask")) == LayerType.FMask


def test_classify_bmask() -> None:
    assert classify_layer(_fake("B.Mask")) == LayerType.BMask


def test_classify_fpaste() -> None:
    assert classify_layer(_fake("F.Paste")) == LayerType.FPaste


def test_classify_bpaste() -> None:
    assert classify_layer(_fake("B.Paste")) == LayerType.BPaste


def test_classify_fsilk() -> None:
    assert classify_layer(_fake("F.SilkS")) == LayerType.FSilk


def test_classify_bsilk() -> None:
    assert classify_layer(_fake("B.SilkS")) == LayerType.BSilk


def test_classify_edge_cuts() -> None:
    assert classify_layer(_fake("Edge.Cuts")) == LayerType.EdgeCuts


def test_classify_npth() -> None:
    assert classify_layer(_fake("NPTH", ".drl")) == LayerType.NPTH


def test_classify_pth() -> None:
    assert classify_layer(_fake("PTH", ".drl")) == LayerType.PTH


def test_classify_npth_beats_pth() -> None:
    """NPTH must be detected before the PTH substring check."""
    assert classify_layer(_fake("board-NPTH", ".drl")) == LayerType.NPTH


def test_classify_drill_fallback() -> None:
    assert classify_layer(_fake("my-drill", ".drl")) == LayerType.Drill


def test_classify_unknown() -> None:
    assert classify_layer(_fake("mystery-layer")) == LayerType.Unknown


def test_classify_legacy_gtl() -> None:
    assert classify_layer(Path("board.gtl")) == LayerType.FCu


def test_classify_legacy_gbl() -> None:
    assert classify_layer(Path("board.gbl")) == LayerType.BCu


def test_classify_legacy_gts() -> None:
    assert classify_layer(Path("board.gts")) == LayerType.FMask


def test_classify_legacy_gto() -> None:
    assert classify_layer(Path("board.gto")) == LayerType.FSilk


# ---------------------------------------------------------------------------
# match_layers -- synthetic directories
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, subdir: str, filenames: list[str]) -> Path:
    d = tmp_path / subdir
    d.mkdir()
    for fn in filenames:
        (d / fn).write_text("")
    return d


def test_match_layers_all_matched(tmp_path: Path) -> None:
    files = ["board-F.Cu.gbr", "board-B.Cu.gbr", "board-Edge.Cuts.gbr"]
    before = _write(tmp_path, "before", files)
    after = _write(tmp_path, "after", files)
    pairs = match_layers(before, after)
    assert len(pairs) == 3
    assert all(p.status == LayerStatus.Matched for p in pairs)


def test_match_layers_added_layer(tmp_path: Path) -> None:
    before = _write(tmp_path, "before", ["board-F.Cu.gbr"])
    after = _write(tmp_path, "after", ["board-F.Cu.gbr", "board-In1.Cu.gbr"])
    pairs = match_layers(before, after)
    statuses = {p.name: p.status for p in pairs}
    assert statuses["board-F.Cu"] == LayerStatus.Matched
    assert statuses["board-In1.Cu"] == LayerStatus.Added


def test_match_layers_removed_layer(tmp_path: Path) -> None:
    before = _write(tmp_path, "before", ["board-F.Cu.gbr", "board-B.Cu.gbr"])
    after = _write(tmp_path, "after", ["board-F.Cu.gbr"])
    pairs = match_layers(before, after)
    statuses = {p.name: p.status for p in pairs}
    assert statuses["board-F.Cu"] == LayerStatus.Matched
    assert statuses["board-B.Cu"] == LayerStatus.Removed
    removed = next(p for p in pairs if p.status == LayerStatus.Removed)
    assert removed.after_path is None
    assert removed.before_path is not None


def test_match_layers_non_layer_files_ignored(tmp_path: Path) -> None:
    before = _write(tmp_path, "before", ["board-F.Cu.gbr", "README.txt", "project.kicad_pcb"])
    after = _write(tmp_path, "after", ["board-F.Cu.gbr"])
    pairs = match_layers(before, after)
    assert len(pairs) == 1


def test_match_layers_empty_dirs(tmp_path: Path) -> None:
    before = _write(tmp_path, "before", [])
    after = _write(tmp_path, "after", [])
    assert match_layers(before, after) == []


def test_match_layers_nonexistent_dir(tmp_path: Path) -> None:
    before = _write(tmp_path, "before", ["board-F.Cu.gbr"])
    after = tmp_path / "nonexistent"
    pairs = match_layers(before, after)
    assert len(pairs) == 1
    assert pairs[0].status == LayerStatus.Removed


def test_match_layers_sort_order(tmp_path: Path) -> None:
    """FCu comes before BCu, which comes before Edge.Cuts."""
    files = ["board-Edge.Cuts.gbr", "board-B.Cu.gbr", "board-F.Cu.gbr"]
    before = _write(tmp_path, "before", files)
    after = _write(tmp_path, "after", files)
    pairs = match_layers(before, after)
    types = [p.layer_type for p in pairs]
    fcu_idx = types.index(LayerType.FCu)
    bcu_idx = types.index(LayerType.BCu)
    ec_idx = types.index(LayerType.EdgeCuts)
    assert fcu_idx < bcu_idx < ec_idx


def test_match_layers_drill_files(tmp_path: Path) -> None:
    files = ["board-NPTH.drl", "board-PTH.drl"]
    before = _write(tmp_path, "before", files)
    after = _write(tmp_path, "after", files)
    pairs = match_layers(before, after)
    types = {p.layer_type for p in pairs}
    assert LayerType.NPTH in types
    assert LayerType.PTH in types


# ---------------------------------------------------------------------------
# match_layers -- real fixtures
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_FIXTURES_BEFORE.exists() and _FIXTURES_AFTER.exists()),
    reason="fixtures not found",
)
def test_match_layers_fixture_dirs() -> None:
    pairs = match_layers(_FIXTURES_BEFORE, _FIXTURES_AFTER)
    assert len(pairs) == 15
    assert all(p.status == LayerStatus.Matched for p in pairs)


@pytest.mark.skipif(not _FIXTURES_BEFORE.exists(), reason="fixture not found")
def test_match_layers_fixture_layer_types() -> None:
    """Every fixture file gets a non-Unknown layer type."""
    pairs = match_layers(_FIXTURES_BEFORE, _FIXTURES_BEFORE)
    for p in pairs:
        assert p.layer_type != LayerType.Unknown, f"{p.name} classified as Unknown"


# ---------------------------------------------------------------------------
# 4.2 -- InCu regex: false-positive prevention
# ---------------------------------------------------------------------------


def test_classify_incu_standard_variants() -> None:
    """Common inner-copper naming patterns all classify as InCu."""
    for stem in ("In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "in1_cu", "board-In2.Cu"):
        result = classify_layer(Path(f"{stem}.gbr"))
        assert result == LayerType.InCu, f"{stem!r} should be InCu, got {result}"


def test_classify_incu_no_false_positive_incident() -> None:
    """'incident_copper' must NOT be classified as InCu."""
    result = classify_layer(_fake("incident_copper"))
    assert result != LayerType.InCu


def test_classify_incu_no_false_positive_no_digit() -> None:
    """'include.cu' (no digit after 'in') must NOT be classified as InCu."""
    result = classify_layer(_fake("include.cu"))
    assert result != LayerType.InCu


def test_classify_incu_no_false_positive_incoming() -> None:
    """'incoming.Cu' contains 'in'+'cu' but no inner-layer pattern -- must not be InCu."""
    result = classify_layer(Path("incoming.Cu.gbr"))
    assert result != LayerType.InCu, f"'incoming.Cu' should not be InCu, got {result}"
