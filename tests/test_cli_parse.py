from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from gerberdelta.cli import cli

_FIXTURES = Path(
    "_reference_gerberdelta_electron/tests/fixtures/gerbers-before/gerbers-before"
)


def test_parse_exits_0_on_valid_gerber() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    runner = CliRunner()
    f = next(_FIXTURES.glob("*.gbr"))
    result = runner.invoke(cli, ["parse", str(f)])
    assert result.exit_code == 0, result.output


def test_parse_exits_nonzero_on_missing_file() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["parse", "nonexistent_file_that_does_not_exist.gbr"])
    assert result.exit_code != 0


def test_parse_dump_ir_is_valid_json() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    runner = CliRunner()
    f = next(_FIXTURES.glob("*.gbr"))
    result = runner.invoke(cli, ["parse", "--dump-ir", str(f)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "net_count" in data
    assert "bounding_box" in data


def test_parse_excellon_exits_0() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    runner = CliRunner()
    f = next(_FIXTURES.glob("*.drl"))
    result = runner.invoke(cli, ["parse", str(f)])
    assert result.exit_code == 0, result.output


def test_parse_quiet_suppresses_output() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    runner = CliRunner()
    f = next(_FIXTURES.glob("*.gbr"))
    result = runner.invoke(cli, ["parse", "-q", str(f)])
    assert result.exit_code == 0
    # -q suppresses nets/bbox lines
    assert "nets:" not in result.output


def test_parse_all_gerbers_exit_0() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    runner = CliRunner()
    for f in sorted(_FIXTURES.glob("*.gbr")):
        result = runner.invoke(cli, ["parse", str(f)])
        assert result.exit_code == 0, f"{f.name}: exit {result.exit_code}\n{result.output}"
