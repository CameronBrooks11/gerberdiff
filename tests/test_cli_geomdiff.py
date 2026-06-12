"""Tests for the `gerberdiff geomdiff` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner, Result

from gerberdiff.cli import cli

_HEADER = "%FSLAX26Y26*%\n%MOIN*%\n"
_FOOTER = "M02*\n"


def _run(*args: str) -> Result:
    runner = CliRunner()
    return runner.invoke(cli, list(args))


def _write_board(directory: Path, pad_x_units: int) -> None:
    """One-layer board with a single 0.1-in pad at the given X (1e-6 in)."""
    directory.mkdir(parents=True, exist_ok=True)
    src = _HEADER + "%ADD10C,0.1*%\nD10*\n" + f"X{pad_x_units}Y0D03*\n" + _FOOTER
    (directory / "board-F.Cu.gbr").write_text(src)


# ---------------------------------------------------------------------------
# Basic invocation
# ---------------------------------------------------------------------------


def test_geomdiff_missing_dir(tmp_path: Path) -> None:
    after = tmp_path / "after"
    after.mkdir()
    result = _run("geomdiff", str(tmp_path / "nonexistent"), str(after))
    assert result.exit_code != 0


def test_geomdiff_empty_dirs_exit_0(tmp_path: Path) -> None:
    before, after = tmp_path / "b", tmp_path / "a"
    before.mkdir()
    after.mkdir()
    result = _run("geomdiff", str(before), str(after))
    assert result.exit_code == 0
    assert "0/0 layers changed" in result.output


def test_geomdiff_identical_no_changes(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 0)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"))
    assert result.exit_code == 0
    assert "0/1 layers changed, 0 changes" in result.output


def test_geomdiff_moved_pad_detected(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)  # 0.1 mm
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"))
    assert result.exit_code == 0
    assert "1/1 layers changed, 1 changes" in result.output


def test_geomdiff_fail_on_diff(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--fail-on-diff")
    assert result.exit_code == 1


def test_geomdiff_fail_on_diff_clean_exit_0(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 0)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--fail-on-diff")
    assert result.exit_code == 0


def test_geomdiff_quiet_suppresses_output(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 0)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "-q")
    assert result.exit_code == 0
    assert result.output == ""


def test_geomdiff_verbose_lists_changes(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "-v")
    assert result.exit_code == 0
    assert "moved flash" in result.output
    assert "d=(" in result.output


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def test_geomdiff_json_report(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    out = tmp_path / "report.json"
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--out-json", str(out))
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert data["version"] == 2
    assert data["mode"] == "geometry"
    assert data["summary"]["total_changes"] == 1
    assert data["tolerances"]["move_tol_mm"] == 0.005
    assert data["layers"][0]["counts"]["moved"] == 1


def test_geomdiff_json_no_overwrite(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 0)
    out = tmp_path / "report.json"
    out.write_text("{}")
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--out-json", str(out))
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_geomdiff_svg_output(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    svg_dir = tmp_path / "svg"
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--out-svg", str(svg_dir))
    assert result.exit_code == 0
    svg_path = svg_dir / "board-F.Cu_geomdiff.svg"
    assert svg_path.exists()
    assert svg_path.read_text().startswith("<svg")


# ---------------------------------------------------------------------------
# Tolerance flags
# ---------------------------------------------------------------------------


def test_geomdiff_move_tol_flag(tmp_path: Path) -> None:
    """Raising --move-tol above the displacement reclassifies as unchanged."""
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)  # 0.1 mm
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--move-tol", "0.15")
    assert result.exit_code == 0
    assert "0 changes" in result.output


def test_geomdiff_gate_radius_flag(tmp_path: Path) -> None:
    """Shrinking --gate-radius below the displacement yields add + remove."""
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--gate-radius", "0.05")
    assert result.exit_code == 0
    assert "2 changes" in result.output


def test_geomdiff_layer_filter(tmp_path: Path) -> None:
    _write_board(tmp_path / "b", 0)
    _write_board(tmp_path / "a", 3937)
    result = _run("geomdiff", str(tmp_path / "b"), str(tmp_path / "a"), "--layer", "no-such-layer")
    assert result.exit_code == 0
    assert "0/0 layers changed" in result.output


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_geomdiff_parse_error_exit_2(tmp_path: Path) -> None:
    before, after = tmp_path / "b", tmp_path / "a"
    before.mkdir()
    after.mkdir()
    # Unknown macro reference is a fatal Error-severity diagnostic.
    bad = _HEADER + "%ADD10NOSUCHMACRO*%\nD10*\nX0Y0D03*\n" + _FOOTER
    (before / "board-F.Cu.gbr").write_text(bad)
    (after / "board-F.Cu.gbr").write_text(bad)
    result = _run("geomdiff", str(before), str(after))
    assert result.exit_code == 2
    assert "error" in result.output.lower()
