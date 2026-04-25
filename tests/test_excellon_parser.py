from __future__ import annotations

from pathlib import Path

import pytest

from gerberdelta.parse.excellon_parser import parse_excellon
from gerberdelta.types import ApertureState, ApertureType, DiagnosticSeverity

_FIXTURES = Path("tests/fixtures/gerbers-before")


def test_parse_minimal_excellon() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.8\n%\nT01\nX1.000Y2.000\nM30\n"
    img = parse_excellon(content)
    assert 1 in img.apertures
    assert img.apertures[1].aperture_type == ApertureType.Circle
    assert len(img.nets) == 1
    assert img.nets[0].aperture_state == ApertureState.Flash


def test_excellon_coordinates_in_inches() -> None:
    # 25.4 mm → 1.0 inch
    content = "M48\nMETRIC,LZ\nT01C25.4\n%\nT01\nX25.4Y0.0\nM30\n"
    img = parse_excellon(content)
    assert abs(img.nets[0].stop_x - 1.0) < 1e-6


def test_excellon_inch_unit_unchanged() -> None:
    content = "M48\nINCH,LZ\nT01C0.1\n%\nT01\nX1.0Y0.5\nM30\n"
    img = parse_excellon(content)
    assert abs(img.nets[0].stop_x - 1.0) < 1e-6
    assert abs(img.nets[0].stop_y - 0.5) < 1e-6


def test_excellon_bbox_valid() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.3\n%\nT01\nX1.0Y2.0\nM30\n"
    img = parse_excellon(content)
    assert img.bounding_box.is_valid


def test_excellon_multiple_tools() -> None:
    content = (
        "M48\nMETRIC,LZ\nT01C0.3\nT02C0.8\n%\n"
        "T01\nX1.0Y1.0\nT02\nX2.0Y2.0\nM30\n"
    )
    img = parse_excellon(content)
    assert 1 in img.apertures
    assert 2 in img.apertures
    assert len(img.nets) == 2


def test_excellon_m30_stops_parsing() -> None:
    content = "M48\nMETRIC,LZ\nT01C0.3\n%\nT01\nX1.0Y1.0\nM30\nX99.0Y99.0\n"
    img = parse_excellon(content)
    # Only the hit before M30 should appear
    assert len(img.nets) == 1


def test_excellon_comment_lines_skipped() -> None:
    content = "M48\n;This is a comment\nMETRIC,LZ\nT01C0.5\n%\nT01\nX1.0Y1.0\nM30\n"
    img = parse_excellon(content)
    assert len(img.nets) == 1
    assert not any(d.severity == DiagnosticSeverity.Error for d in img.diagnostics)


def test_excellon_no_crash_on_fixture_drill_files() -> None:
    if not _FIXTURES.exists():
        pytest.skip("fixture directory not present")
    for f in sorted(_FIXTURES.glob("*.drl")):
        img = parse_excellon(f.read_text(errors="replace"), source_path=f)
        errors = [d for d in img.diagnostics if d.severity == DiagnosticSeverity.Error]
        assert errors == [], f"{f.name}: {errors}"
        assert img.bounding_box.is_valid, f"{f.name}: bounding box not valid"
