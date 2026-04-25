"""Tests for export/json_report.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gerberdelta.export.json_report import build_report, write_report
from gerberdelta.types import (
    BoundingBox,
    DiffResult,
    LayerDiffResult,
    LayerStatus,
    LayerType,
    Region,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bbox(
    min_x: float = 0.0, min_y: float = 0.0, max_x: float = 1.0, max_y: float = 1.0
) -> BoundingBox:
    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _region(rid: int = 1, px: int = 100) -> Region:
    return Region(
        id=rid,
        centroid_x=0.5,
        centroid_y=0.5,
        bounding_box=_bbox(),
        pixel_count=px,
    )


def _layer(
    name: str = "F.Cu",
    status: LayerStatus = LayerStatus.Matched,
    changed: int = 100,
    total: int = 1000,
    regions: list[Region] | None = None,
    layer_type: LayerType = LayerType.FCu,
) -> LayerDiffResult:
    return LayerDiffResult(
        name=name,
        status=status,
        layer_type=layer_type,
        changed_pixel_count=changed,
        total_pixel_count=total,
        regions=regions or [],
    )


def _diff(*layers: LayerDiffResult) -> DiffResult:
    return DiffResult(layers=list(layers))


# ---------------------------------------------------------------------------
# build_report structure
# ---------------------------------------------------------------------------


def test_build_report_version() -> None:
    report = build_report(_diff())
    assert report["version"] == 1


def test_build_report_generator() -> None:
    report = build_report(_diff())
    assert report["generator"] == "gerberdelta"


def test_build_report_summary_no_changes() -> None:
    dr = _diff(_layer(changed=0))
    report = build_report(dr)
    assert report["summary"]["has_changes"] is False
    assert report["summary"]["changed_layers"] == 0
    assert report["summary"]["total_regions"] == 0


def test_build_report_summary_with_changes() -> None:
    r = _region()
    dr = _diff(_layer(changed=50, regions=[r]))
    report = build_report(dr)
    assert report["summary"]["has_changes"] is True
    assert report["summary"]["changed_layers"] == 1
    assert report["summary"]["total_regions"] == 1


def test_build_report_layer_fields() -> None:
    dr = _diff(_layer(name="B.Cu", status=LayerStatus.Matched, changed=200, total=4000))
    layer = build_report(dr)["layers"][0]
    assert layer["name"] == "B.Cu"
    assert layer["status"] == "matched"
    assert layer["changed_pixel_count"] == 200
    assert layer["total_pixel_count"] == 4000
    assert layer["changed_fraction"] == pytest.approx(0.05)


def test_build_report_added_layer() -> None:
    dr = _diff(_layer(name="In1.Cu", status=LayerStatus.Added, layer_type=LayerType.InCu, changed=1000, total=1000))
    report = build_report(dr)
    assert report["summary"]["changed_layers"] == 1
    assert report["layers"][0]["status"] == "added"


def test_build_report_region_fields() -> None:
    r = Region(
        id=3,
        centroid_x=1.2,
        centroid_y=3.4,
        bounding_box=_bbox(1.0, 3.0, 1.4, 3.8),
        pixel_count=42,
    )
    dr = _diff(_layer(regions=[r]))
    region_out = build_report(dr)["layers"][0]["regions"][0]
    assert region_out["id"] == 3
    assert region_out["centroid_x"] == pytest.approx(1.2)
    assert region_out["centroid_y"] == pytest.approx(3.4)
    assert region_out["pixel_count"] == 42
    assert region_out["bbox"]["min_x"] == pytest.approx(1.0)
    assert region_out["bbox"]["max_y"] == pytest.approx(3.8)


def test_build_report_json_serialisable() -> None:
    r = _region()
    dr = _diff(_layer(regions=[r]))
    # Must not raise
    text = json.dumps(build_report(dr))
    parsed = json.loads(text)
    assert parsed["version"] == 1


def test_build_report_multiple_layers() -> None:
    dr = _diff(
        _layer("F.Cu", changed=10, total=100),
        _layer("B.Cu", changed=0, total=100),
    )
    report = build_report(dr)
    assert len(report["layers"]) == 2
    assert report["summary"]["changed_layers"] == 1


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def test_write_report_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    write_report(_diff(_layer()), out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["version"] == 1


def test_write_report_no_overwrite_raises(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    out.write_text("{}")
    with pytest.raises(FileExistsError):
        write_report(_diff(_layer()), out, overwrite=False)


def test_write_report_overwrite_allowed(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    out.write_text("{}")
    write_report(_diff(_layer(changed=5)), out, overwrite=True)
    data = json.loads(out.read_text())
    assert data["version"] == 1


def test_write_report_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "sub" / "deep" / "report.json"
    write_report(_diff(), out)
    assert out.exists()
