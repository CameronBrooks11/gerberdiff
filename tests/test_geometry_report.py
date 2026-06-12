"""Tests for the geometry JSON report (schema v2) and SVG export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from gerberdiff.export.json_report import build_geometry_report, write_geometry_report
from gerberdiff.export.svg_export import render_geometry_svg, write_geometry_svg
from gerberdiff.geometry.types import GeometryChange, GeometryDiffResult, LayerGeometryDiff
from gerberdiff.types import LayerStatus, LayerType


def _sample_result() -> GeometryDiffResult:
    moved = GeometryChange(
        kind="moved",
        op_kind="flash",
        centroid_x=1.0,
        centroid_y=2.0,
        area_mm2=0.5,
        dx_mm=0.1,
        dy_mm=-0.05,
        net_name="VCC",
        before_geom=Point(0.996, 2.002).buffer(0.01),
        after_geom=Point(1.0, 2.0).buffer(0.01),
    )
    added = GeometryChange(
        kind="added",
        op_kind="flash",
        centroid_x=0.5,
        centroid_y=0.5,
        area_mm2=0.25,
        after_geom=box(0.49, 0.49, 0.51, 0.51),
    )
    removed = GeometryChange(
        kind="removed",
        op_kind="stroke",
        centroid_x=0.2,
        centroid_y=0.8,
        area_mm2=0.1,
        before_geom=box(0.15, 0.79, 0.25, 0.81),
    )
    resized = GeometryChange(
        kind="resized",
        op_kind="flash",
        centroid_x=0.3,
        centroid_y=0.3,
        area_mm2=0.3,
        dx_mm=0.0,
        dy_mm=0.0,
        before_geom=Point(0.3, 0.3).buffer(0.012),
        after_geom=Point(0.3, 0.3).buffer(0.01),
    )
    layer = LayerGeometryDiff(
        name="F.Cu",
        layer_type=LayerType.FCu,
        status=LayerStatus.Matched,
        changes=[moved, added, removed, resized],
        unchanged_count=100,
        added_area_mm2=0.75,
        removed_area_mm2=0.6,
    )
    quiet = LayerGeometryDiff(
        name="Edge.Cuts",
        layer_type=LayerType.EdgeCuts,
        status=LayerStatus.Matched,
        unchanged_count=10,
    )
    return GeometryDiffResult(layers=[layer, quiet])


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


def test_report_version_and_mode() -> None:
    report = build_geometry_report(_sample_result())
    assert report["version"] == 2
    assert report["mode"] == "geometry"
    assert report["generator"] == "gerberdiff"


def test_report_summary() -> None:
    report = build_geometry_report(_sample_result())
    assert report["summary"] == {
        "changed_layers": 1,
        "total_changes": 4,
        "has_changes": True,
    }


def test_report_layer_counts() -> None:
    report = build_geometry_report(_sample_result())
    layer = report["layers"][0]
    assert layer["name"] == "F.Cu"
    assert layer["counts"] == {"added": 1, "removed": 1, "moved": 1, "resized": 1}
    assert layer["unchanged_count"] == 100
    assert layer["added_area_mm2"] == 0.75


def test_report_change_fields() -> None:
    report = build_geometry_report(_sample_result())
    changes = report["layers"][0]["changes"]
    moved = next(c for c in changes if c["kind"] == "moved")
    assert moved["op_kind"] == "flash"
    assert moved["dx_mm"] == 0.1
    assert moved["dy_mm"] == -0.05
    assert moved["net"] == "VCC"
    added = next(c for c in changes if c["kind"] == "added")
    assert added["dx_mm"] is None
    assert added["net"] is None


def test_report_tolerances_recorded() -> None:
    tol = {"move_tol_mm": 0.005, "gate_radius_mm": 0.2, "area_tol": 0.01, "dust_area_mm2": 1e-6}
    report = build_geometry_report(_sample_result(), tolerances=tol)
    assert report["tolerances"] == tol


def test_report_json_serializable() -> None:
    report = build_geometry_report(_sample_result())
    json.dumps(report)  # must not raise (geoms excluded)


def test_write_report_and_overwrite_guard(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    write_geometry_report(_sample_result(), out)
    data = json.loads(out.read_text())
    assert data["version"] == 2
    with pytest.raises(FileExistsError):
        write_geometry_report(_sample_result(), out)
    write_geometry_report(_sample_result(), out, overwrite=True)


# ---------------------------------------------------------------------------
# SVG export
# ---------------------------------------------------------------------------


def test_svg_contains_all_change_kinds() -> None:
    svg = render_geometry_svg(_sample_result().layers[0])
    assert svg.startswith("<svg")
    assert "#cc0000" in svg  # removed
    assert "#00aa00" in svg  # added
    assert "#0066cc" in svg  # moved (fill + displacement line)
    assert "#cc6600" in svg  # resized
    assert "<line" in svg


def test_svg_no_changes_minimal_document() -> None:
    svg = render_geometry_svg(_sample_result().layers[1])
    assert svg.startswith("<svg")
    assert "no changes" in svg


def test_svg_holes_use_evenodd() -> None:
    annulus = Point(0.0, 0.0).buffer(0.1).difference(Point(0.0, 0.0).buffer(0.05))
    change = GeometryChange(
        kind="added",
        op_kind="flash",
        centroid_x=0.0,
        centroid_y=0.0,
        area_mm2=1.0,
        after_geom=annulus,
    )
    layer = LayerGeometryDiff(
        name="L",
        layer_type=LayerType.Unknown,
        status=LayerStatus.Matched,
        changes=[change],
    )
    svg = render_geometry_svg(layer)
    assert "fill-rule='evenodd'" in svg
    # Two rings -> two M..Z subpaths within the path data.
    assert svg.count("M ") >= 2


def test_write_svg_and_overwrite_guard(tmp_path: Path) -> None:
    out = tmp_path / "layer.svg"
    write_geometry_svg(_sample_result().layers[0], out)
    assert out.read_text().startswith("<svg")
    with pytest.raises(FileExistsError):
        write_geometry_svg(_sample_result().layers[0], out)
    write_geometry_svg(_sample_result().layers[0], out, overwrite=True)
