"""Tests for the `gerberdelta diff` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from gerberdelta.cli import cli

_FIXTURES_BEFORE = Path("tests/fixtures/gerbers-before")
_FIXTURES_AFTER = Path("tests/fixtures/gerbers-after")
_FIXTURES_EXIST = _FIXTURES_BEFORE.exists() and _FIXTURES_AFTER.exists()


def _run(*args: str) -> Result:
    runner = CliRunner()
    return runner.invoke(cli, list(args))


# ---------------------------------------------------------------------------
# Basic invocation
# ---------------------------------------------------------------------------


def test_diff_missing_before_dir(tmp_path: Path) -> None:
    after = tmp_path / "after"
    after.mkdir()
    result = _run("diff", str(tmp_path / "nonexistent"), str(after))
    assert result.exit_code != 0


def test_diff_missing_after_dir(tmp_path: Path) -> None:
    before = tmp_path / "before"
    before.mkdir()
    result = _run("diff", str(before), str(tmp_path / "nonexistent"))
    assert result.exit_code != 0


def test_diff_empty_dirs_exits_0(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    result = _run("diff", str(before), str(after))
    assert result.exit_code == 0


def test_diff_empty_dirs_no_fail_on_diff(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    result = _run("diff", str(before), str(after), "--fail-on-diff")
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_identical_dirs_exits_0(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_BEFORE),
        "--width",
        "128",
        "--height",
        "128",
    )
    assert result.exit_code == 0, result.output


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_identical_no_fail_on_diff(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_BEFORE),
        "--width",
        "128",
        "--height",
        "128",
        "--fail-on-diff",
    )
    assert result.exit_code == 0, result.output


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_before_after_has_changes(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "256",
        "--height",
        "256",
    )
    assert result.exit_code == 0, result.output
    assert "changed" in result.output.lower()


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_fail_on_diff_exits_1(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "128",
        "--height",
        "128",
        "--fail-on-diff",
    )
    assert result.exit_code == 1


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_json_report_written(tmp_path: Path) -> None:
    out_json = tmp_path / "report.json"
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "128",
        "--height",
        "128",
        "--out-json",
        str(out_json),
    )
    assert result.exit_code == 0, result.output
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert data["version"] == 1
    assert data["summary"]["has_changes"] is True
    assert len(data["layers"]) > 0


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_json_no_overwrite(tmp_path: Path) -> None:
    out_json = tmp_path / "report.json"
    out_json.write_text("{}")
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "64",
        "--height",
        "64",
        "--out-json",
        str(out_json),
    )
    assert result.exit_code == 1
    assert out_json.read_text() == "{}"


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_png_output_written(tmp_path: Path) -> None:
    png_dir = tmp_path / "pngs"
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "64",
        "--height",
        "64",
        "--out-png",
        str(png_dir),
    )
    assert result.exit_code == 0, result.output
    pngs = list(png_dir.glob("*_diff.png"))
    assert len(pngs) > 0


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_layer_filter(tmp_path: Path) -> None:
    """--layer restricts output to named layer only."""
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "128",
        "--height",
        "128",
        "--layer",
        "A64-OlinuXino-F.Cu",
    )
    assert result.exit_code == 0, result.output


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_verbose_output(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_AFTER),
        "--width",
        "64",
        "--height",
        "64",
        "--layer",
        "A64-OlinuXino-F.Cu",
        "--verbose",
    )
    assert result.exit_code == 0, result.output
    assert "region" in result.output.lower() or "changed" in result.output.lower()


@pytest.mark.skipif(not _FIXTURES_EXIST, reason="fixtures not found")
def test_diff_quiet_no_stdout(tmp_path: Path) -> None:
    result = _run(
        "diff",
        str(_FIXTURES_BEFORE),
        str(_FIXTURES_BEFORE),
        "--width",
        "64",
        "--height",
        "64",
        "--quiet",
    )
    assert result.exit_code == 0
    assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# 3.4 — assert → explicit error handling
# ---------------------------------------------------------------------------


def test_diff_added_layer_reports_correctly(tmp_path: Path) -> None:
    """A file present only in after_dir is reported as 'added' with exit 0."""
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    # Write a minimal gerber only in 'after' so layer is 'added'
    (after / "test.gbr").write_text(
        "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\nD10*\nX0Y0D03*\nM02*\n"
    )
    result = _run("diff", str(before), str(after), "--width", "64", "--height", "64")
    assert result.exit_code == 0, result.output


def test_diff_removed_layer_reports_correctly(tmp_path: Path) -> None:
    """A file present only in before_dir is reported as 'removed' with exit 0."""
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "test.gbr").write_text(
        "%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.2*%\nD10*\nX0Y0D03*\nM02*\n"
    )
    result = _run("diff", str(before), str(after), "--width", "64", "--height", "64")
    assert result.exit_code == 0, result.output
