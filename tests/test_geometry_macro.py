"""Tests for geometry/macro_geom.py: macro primitives -> shapely geometry."""

from __future__ import annotations

import math

import pytest

import gerberdiff.geometry.macro_geom as macro_geom
from gerberdiff.geometry.macro_geom import macro_flash_geometry
from gerberdiff.parse.macro_parser import parse_macro_body
from gerberdiff.types import DiagnosticSeverity, MacroAperture


def _aperture(
    body: str, params: list[float] | None = None, unit_scale: float = 1.0
) -> MacroAperture:
    return MacroAperture(
        macro_def=parse_macro_body("TEST", body),
        params=params or [],
        unit_scale=unit_scale,
    )


# ---------------------------------------------------------------------------
# Individual primitives
# ---------------------------------------------------------------------------


def test_circle_primitive_area() -> None:
    geom, diags = macro_flash_geometry(_aperture("1,1,0.05,0,0,0"), 0.0, 0.0)
    assert not diags
    assert math.isclose(geom.area, math.pi * 0.025**2, rel_tol=5e-3)


def test_circle_primitive_offset_centre_and_flash_position() -> None:
    geom, _ = macro_flash_geometry(_aperture("1,1,0.02,0.1,0.0,0"), 1.0, 2.0)
    c = geom.centroid
    assert math.isclose(c.x, 1.1, abs_tol=1e-9)
    assert math.isclose(c.y, 2.0, abs_tol=1e-9)


def test_line_vector_area() -> None:
    # width=0.05 from (-0.1, 0) to (0.1, 0): rectangle 0.2 x 0.05
    geom, _ = macro_flash_geometry(_aperture("20,1,0.05,-0.1,0,0.1,0,0"), 0.0, 0.0)
    assert math.isclose(geom.area, 0.2 * 0.05, rel_tol=1e-9)


def test_line_vector_rotation_about_origin() -> None:
    """90-degree rotation maps an X-axis bar onto the Y axis."""
    geom, _ = macro_flash_geometry(_aperture("20,1,0.05,0.1,0,0.2,0,90"), 0.0, 0.0)
    minx, miny, maxx, maxy = geom.bounds
    assert math.isclose(miny, 0.1, abs_tol=1e-9)
    assert math.isclose(maxy, 0.2, abs_tol=1e-9)
    assert math.isclose(minx, -0.025, abs_tol=1e-9)
    assert math.isclose(maxx, 0.025, abs_tol=1e-9)


def test_line_center_area() -> None:
    geom, _ = macro_flash_geometry(_aperture("21,1,0.1,0.04,0,0,0"), 0.0, 0.0)
    assert math.isclose(geom.area, 0.1 * 0.04, rel_tol=1e-9)


def test_outline_triangle_area() -> None:
    # Right triangle with legs 0.1: area 0.005.  Outline closes back to start.
    body = "4,1,3,0,0,0.1,0,0,0.1,0,0,0"
    geom, _ = macro_flash_geometry(_aperture(body), 0.0, 0.0)
    assert math.isclose(geom.area, 0.005, rel_tol=1e-9)


def test_polygon_primitive_area() -> None:
    # Hexagon, diameter 0.2 -> R = 0.1
    geom, _ = macro_flash_geometry(_aperture("5,1,6,0,0,0.2,0"), 0.0, 0.0)
    expected = 0.5 * 6 * 0.1 * 0.1 * math.sin(2.0 * math.pi / 6)
    assert math.isclose(geom.area, expected, rel_tol=1e-9)


def test_moire_area_bounded_by_annulus_and_disc() -> None:
    # outer dia 0.2, ring thickness 0.02, gap 0.02, 3 rings, crosshair 0.01x0.15
    body = "6,0,0,0.2,0.02,0.02,3,0.01,0.15,0"
    geom, _ = macro_flash_geometry(_aperture(body), 0.0, 0.0)
    full_disc = math.pi * 0.1**2
    outer_ring = math.pi * (0.1**2 - 0.08**2)
    assert outer_ring < geom.area < full_disc


def test_thermal_area() -> None:
    # outer dia 0.2, inner dia 0.12, gap 0.02
    geom, _ = macro_flash_geometry(_aperture("7,0,0,0.2,0.12,0.02,0"), 0.0, 0.0)
    annulus = math.pi * (0.1**2 - 0.06**2)
    # Each of two perpendicular bars removes ~2 * (R - r) * gap from the ring.
    gap_loss = 2 * 2 * (0.1 - 0.06) * 0.02
    assert math.isclose(geom.area, annulus - gap_loss, rel_tol=0.05)


def test_thermal_zero_gap_is_annulus() -> None:
    geom, _ = macro_flash_geometry(_aperture("7,0,0,0.2,0.12,0,0"), 0.0, 0.0)
    annulus = math.pi * (0.1**2 - 0.06**2)
    assert math.isclose(geom.area, annulus, rel_tol=5e-3)


# ---------------------------------------------------------------------------
# Exposure composition
# ---------------------------------------------------------------------------


def test_exposure_zero_subtracts_within_macro() -> None:
    """Dark disc + clear smaller disc = annulus."""
    body = "1,1,0.1,0,0,0*1,0,0.05,0,0,0"
    geom, _ = macro_flash_geometry(_aperture(body), 0.0, 0.0)
    expected = math.pi * (0.05**2 - 0.025**2)
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


def test_exposure_zero_then_dark_re_adds() -> None:
    """Erased area can be re-exposed by a later dark primitive."""
    body = "1,1,0.1,0,0,0*1,0,0.1,0,0,0*1,1,0.04,0,0,0"
    geom, _ = macro_flash_geometry(_aperture(body), 0.0, 0.0)
    assert math.isclose(geom.area, math.pi * 0.02**2, rel_tol=5e-3)


def test_exposure_zero_only_produces_empty() -> None:
    geom, diags = macro_flash_geometry(_aperture("1,0,0.05,0,0,0"), 0.0, 0.0)
    assert geom.is_empty
    assert not diags


# ---------------------------------------------------------------------------
# Parameters and scaling
# ---------------------------------------------------------------------------


def test_parameter_substitution() -> None:
    geom, _ = macro_flash_geometry(_aperture("1,1,$1,0,0,0", params=[0.08]), 0.0, 0.0)
    assert math.isclose(geom.area, math.pi * 0.04**2, rel_tol=5e-3)


def test_assignment_statement() -> None:
    geom, _ = macro_flash_geometry(_aperture("$2=$1x2*1,1,$2,0,0,0", params=[0.03]), 0.0, 0.0)
    assert math.isclose(geom.area, math.pi * 0.03**2, rel_tol=5e-3)


def test_unit_scale_applied() -> None:
    """A mm-file macro (unit_scale = 1/25.4) shrinks into inch space."""
    scale = 1.0 / 25.4
    geom, _ = macro_flash_geometry(_aperture("1,1,1.0,0,0,0", unit_scale=scale), 0.0, 0.0)
    expected = math.pi * (0.5 * scale) ** 2
    assert math.isclose(geom.area, expected, rel_tol=5e-3)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_no_macro_def_returns_empty() -> None:
    ap = MacroAperture(macro_def=None, params=[])
    geom, diags = macro_flash_geometry(ap, 0.0, 0.0)
    assert geom.is_empty
    assert not diags


def test_evaluation_failure_warns_and_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """A macro that fails to evaluate yields empty geometry + Warning."""

    def _boom(*args: object, **kwargs: object) -> list[object]:
        raise ValueError("synthetic evaluation failure")

    monkeypatch.setattr(macro_geom, "evaluate_macro_primitives", _boom)
    geom, diags = macro_flash_geometry(_aperture("1,1,0.05,0,0,0"), 0.0, 0.0)
    assert geom.is_empty
    assert len(diags) == 1
    assert diags[0].severity == DiagnosticSeverity.Warning
    assert "evaluation failed" in diags[0].message


def test_degenerate_primitives_skipped() -> None:
    """Zero-diameter circle and zero-length vector produce nothing."""
    geom, diags = macro_flash_geometry(_aperture("1,1,0,0,0,0*20,1,0.05,0,0,0,0,0"), 0.0, 0.0)
    assert geom.is_empty
    assert not diags
