"""Tests for the `gerberdelta render` CLI subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from gerberdelta.cli import cli

_FIXTURES = Path(__file__).parent / "fixtures" / "gerbers-before"
_FCU = _FIXTURES / "A64-OlinuXino-F.Cu.gbr"
_NPTH = _FIXTURES / "A64-OlinuXino-NPTH.drl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args: str) -> Result:
    runner = CliRunner()
    return runner.invoke(cli, list(args))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_render_missing_file(tmp_path: Path) -> None:
    out = tmp_path / "out.png"
    result = _run("render", "nonexistent.gbr", "--out-png", str(out))
    assert result.exit_code != 0


def test_render_requires_out_png(tmp_path: Path) -> None:
    """--out-png is required; omitting it should produce a usage error."""
    result = _run("render", str(_FCU) if _FCU.exists() else "nonexistent.gbr")
    assert result.exit_code != 0


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_produces_png(tmp_path: Path) -> None:
    out = tmp_path / "fcu.png"
    result = _run("render", str(_FCU), "--out-png", str(out), "--width", "256", "--height", "256")
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.stat().st_size > 1000


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_no_overwrite_by_default(tmp_path: Path) -> None:
    out = tmp_path / "fcu.png"
    out.write_bytes(b"existing")
    result = _run("render", str(_FCU), "--out-png", str(out), "--width", "64", "--height", "64")
    assert result.exit_code == 1
    # Original file untouched
    assert out.read_bytes() == b"existing"


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_overwrite_flag(tmp_path: Path) -> None:
    out = tmp_path / "fcu.png"
    out.write_bytes(b"existing")
    result = _run(
        "render",
        str(_FCU),
        "--out-png",
        str(out),
        "--width",
        "64",
        "--height",
        "64",
        "--overwrite",
    )
    assert result.exit_code == 0, result.output
    assert out.stat().st_size > 100


@pytest.mark.skipif(not _NPTH.exists(), reason="fixture not found")
def test_render_excellon_drill(tmp_path: Path) -> None:
    out = tmp_path / "npth.png"
    result = _run("render", str(_NPTH), "--out-png", str(out), "--width", "128", "--height", "128")
    assert result.exit_code == 0, result.output
    assert out.exists()


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_memory_warning(tmp_path: Path) -> None:
    """Canvas > 4096x4096 should print a warning to stderr but still succeed."""
    out = tmp_path / "big.png"
    result = _run(
        "render",
        str(_FCU),
        "--out-png",
        str(out),
        "--width",
        "4097",
        "--height",
        "4097",
    )
    # Warning goes to stderr; exit should be 0
    assert result.exit_code == 0, result.output
    assert out.exists()


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_verbose_output(tmp_path: Path) -> None:
    out = tmp_path / "fcu.png"
    result = _run(
        "render",
        str(_FCU),
        "--out-png",
        str(out),
        "--width",
        "128",
        "--height",
        "128",
        "--verbose",
    )
    assert result.exit_code == 0, result.output
    assert "render time" in result.output
    assert "nets" in result.output


@pytest.mark.skipif(not _FCU.exists(), reason="fixture not found")
def test_render_quiet_no_stdout(tmp_path: Path) -> None:
    out = tmp_path / "fcu.png"
    result = _run(
        "render",
        str(_FCU),
        "--out-png",
        str(out),
        "--width",
        "128",
        "--height",
        "128",
        "--quiet",
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""
