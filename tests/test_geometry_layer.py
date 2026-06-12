"""Tests for geometry/layer_geometry.py: assembly, polarity, transforms.

Includes a differential test pinning the geometry engine's transform and
polarity semantics to the battle-tested Cairo renderer.
"""

from __future__ import annotations

import math

import numpy as np
from shapely import contains_xy

from gerberdiff.geometry.layer_geometry import build_layer_geometry, resolve_geometry
from gerberdiff.parse.gerber_state import parse_gerber
from gerberdiff.types import Polarity

_HEADER = "%FSLAX25Y25*%\n%MOIN*%\n"
_FOOTER = "M02*\n"


def _gerber(*body_lines: str) -> str:
    return _HEADER + "\n".join(body_lines) + "\n" + _FOOTER


# ---------------------------------------------------------------------------
# Basic assembly
# ---------------------------------------------------------------------------


def test_flash_and_stroke_kinds() -> None:
    src = _gerber(
        "%ADD10C,0.1*%",
        "D10*",
        "X0Y0D03*",
        "X0Y0D02*",
        "X100000Y0D01*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    kinds = [op.kind for op in lg.ops]
    assert kinds == ["flash", "stroke"]
    assert all(op.polarity == Polarity.Dark for op in lg.ops)
    assert not lg.has_clear


def test_signatures_stable_across_identical_parses() -> None:
    src = _gerber("%ADD10C,0.1*%", "D10*", "X50000Y50000D03*")
    lg1 = build_layer_geometry(parse_gerber(src))
    lg2 = build_layer_geometry(parse_gerber(src))
    assert lg1.ops[0].signature == lg2.ops[0].signature


def test_signature_independent_of_d_code() -> None:
    """The same pad via a different D-code number cancels identically."""
    src_a = _gerber("%ADD10C,0.1*%", "D10*", "X50000Y50000D03*")
    src_b = _gerber("%ADD99C,0.1*%", "D99*", "X50000Y50000D03*")
    lg_a = build_layer_geometry(parse_gerber(src_a))
    lg_b = build_layer_geometry(parse_gerber(src_b))
    assert lg_a.ops[0].signature == lg_b.ops[0].signature


def test_net_attribute_propagates() -> None:
    src = _gerber(
        "%ADD10C,0.1*%",
        "D10*",
        "%TO.N,VCC*%",
        "X0Y0D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.ops[0].net_name == "VCC"


def test_region_fill_assembled() -> None:
    src = _gerber(
        "G36*",
        "X0Y0D02*",
        "X100000Y0D01*",
        "X100000Y100000D01*",
        "X0Y100000D01*",
        "X0Y0D01*",
        "G37*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert [op.kind for op in lg.ops] == ["region"]
    assert math.isclose(lg.ops[0].area, 1.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Polarity replay
# ---------------------------------------------------------------------------


def test_clear_polarity_subtracts() -> None:
    """Dark square region, then clear circle punched out of it."""
    src = _gerber(
        "%ADD10C,0.2*%",
        "G36*",
        "X0Y0D02*",
        "X100000Y0D01*",
        "X100000Y100000D01*",
        "X0Y100000D01*",
        "X0Y0D01*",
        "G37*",
        "%LPC*%",
        "D10*",
        "X50000Y50000D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.has_clear
    resolved = resolve_geometry(lg.ops)
    expected = 1.0 - math.pi * 0.1**2
    assert math.isclose(resolved.area, expected, rel_tol=5e-3)


def test_dark_after_clear_re_adds() -> None:
    """Clear erases, but a later dark layer can draw over the hole."""
    src = _gerber(
        "%ADD10C,0.2*%",
        "%ADD11C,0.1*%",
        "G36*",
        "X0Y0D02*",
        "X100000Y0D01*",
        "X100000Y100000D01*",
        "X0Y100000D01*",
        "X0Y0D01*",
        "G37*",
        "%LPC*%",
        "D10*",
        "X50000Y50000D03*",
        "%LPD*%",
        "D11*",
        "X50000Y50000D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    resolved = resolve_geometry(lg.ops)
    expected = 1.0 - math.pi * 0.1**2 + math.pi * 0.05**2
    assert math.isclose(resolved.area, expected, rel_tol=5e-3)


def test_clear_with_nothing_underneath() -> None:
    src = _gerber("%ADD10C,0.2*%", "%LPC*%", "D10*", "X0Y0D03*")
    lg = build_layer_geometry(parse_gerber(src))
    resolved = resolve_geometry(lg.ops)
    assert resolved.is_empty


# ---------------------------------------------------------------------------
# Layer transforms
# ---------------------------------------------------------------------------


def test_rotation_transform() -> None:
    """%LR90% applied before drawing rotates positions about the origin."""
    src = _gerber("%ADD10C,0.1*%", "%LR90*%", "D10*", "X100000Y0D03*")
    lg = build_layer_geometry(parse_gerber(src))
    op = lg.ops[0]
    assert math.isclose(op.centroid_x, 0.0, abs_tol=1e-9)
    assert math.isclose(op.centroid_y, 1.0, abs_tol=1e-9)


def test_mirror_transform() -> None:
    """%LMX% (FlipA) negates X."""
    src = _gerber("%ADD10C,0.1*%", "%LMX*%", "D10*", "X100000Y50000D03*")
    lg = build_layer_geometry(parse_gerber(src))
    op = lg.ops[0]
    assert math.isclose(op.centroid_x, -1.0, abs_tol=1e-9)
    assert math.isclose(op.centroid_y, 0.5, abs_tol=1e-9)


def test_scale_transform() -> None:
    """%LS2% doubles positions and dimensions."""
    src = _gerber("%ADD10C,0.1*%", "%LS2*%", "D10*", "X100000Y0D03*")
    lg = build_layer_geometry(parse_gerber(src))
    op = lg.ops[0]
    assert math.isclose(op.centroid_x, 2.0, abs_tol=1e-9)
    assert math.isclose(op.area, math.pi * 0.1**2, rel_tol=5e-3)  # r doubled


# ---------------------------------------------------------------------------
# Step and repeat
# ---------------------------------------------------------------------------


def test_step_repeat_tiles() -> None:
    src = _gerber("%SRX2Y3I1.0J2.0*%", "%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    lg = build_layer_geometry(parse_gerber(src))
    assert len(lg.ops) == 6
    xs = sorted(round(op.centroid_x, 6) for op in lg.ops)
    ys = sorted(round(op.centroid_y, 6) for op in lg.ops)
    assert xs == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    assert ys == [0.0, 0.0, 2.0, 2.0, 4.0, 4.0]


def test_step_repeat_tiles_have_distinct_signatures() -> None:
    src = _gerber("%SRX2Y1I0.5J0*%", "%ADD10C,0.1*%", "D10*", "X0Y0D03*")
    lg = build_layer_geometry(parse_gerber(src))
    sigs = {op.signature for op in lg.ops}
    assert len(sigs) == 2


# ---------------------------------------------------------------------------
# Block apertures
# ---------------------------------------------------------------------------


def test_block_flash_translates_content() -> None:
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X0Y0D03*",
        "%AB*%",
        "D10*",
        "X100000Y200000D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert len(lg.ops) == 1
    op = lg.ops[0]
    assert math.isclose(op.centroid_x, 1.0, abs_tol=1e-9)
    assert math.isclose(op.centroid_y, 2.0, abs_tol=1e-9)
    assert math.isclose(op.area, math.pi * 0.05**2, rel_tol=5e-3)


def test_block_flashed_twice() -> None:
    src = _gerber(
        "%ADD11C,0.1*%",
        "%ABD10*%",
        "D11*",
        "X0Y0D03*",
        "%AB*%",
        "D10*",
        "X0Y0D03*",
        "X100000Y0D03*",
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert len(lg.ops) == 2
    xs = sorted(op.centroid_x for op in lg.ops)
    assert math.isclose(xs[0], 0.0, abs_tol=1e-9)
    assert math.isclose(xs[1], 1.0, abs_tol=1e-9)


def test_clear_inside_block_erases_globally() -> None:
    """A clear layer inside a block subtracts from material drawn before
    the block flash (verified renderer semantics)."""
    src = _gerber(
        "%ADD10C,0.4*%",
        "%ADD12C,0.2*%",
        "D10*",
        "X0Y0D03*",  # big dark disc first
        "%ABD11*%",
        "%LPC*%",
        "D12*",
        "X0Y0D03*",  # clear disc inside the block
        "%AB*%",
        "%LPD*%",
        "D11*",
        "X0Y0D03*",  # flash the block centred on the disc
    )
    lg = build_layer_geometry(parse_gerber(src))
    assert lg.has_clear
    resolved = resolve_geometry(lg.ops)
    expected = math.pi * (0.2**2 - 0.1**2)
    assert math.isclose(resolved.area, expected, rel_tol=5e-3)


# ---------------------------------------------------------------------------
# Differential test against the Cairo renderer
# ---------------------------------------------------------------------------


def test_geometry_matches_renderer_occupancy() -> None:
    """Resolved geometry must agree with the raster renderer pixel-for-pixel
    (>= 99% on a sample grid; anti-aliased edge pixels may differ)."""
    from gerberdiff.render.renderer import render_to_numpy
    from gerberdiff.render.viewport import compute_viewport, screen_to_world

    src = _gerber(
        "%ADD10C,0.08*%",
        "%ADD11R,0.12X0.06*%",
        "D10*",
        "X0Y0D03*",
        "X20000Y10000D03*",
        "D11*",
        "X10000Y20000D03*",
        "X0Y0D02*",
        "D10*",
        "X20000Y20000D01*",
        "%LPC*%",
        "D10*",
        "X10000Y10000D03*",
    )
    parsed = parse_gerber(src)
    lg = build_layer_geometry(parsed)
    resolved = resolve_geometry(lg.ops)

    size = 256
    vp = compute_viewport(parsed.bounding_box, size, size)
    arr = render_to_numpy(parsed, vp)
    raster_occ = arr[..., 3] > 127  # opaque -> material

    xs = np.empty((size, size))
    ys = np.empty((size, size))
    for py in range(size):
        for px in range(size):
            wx, wy = screen_to_world(px + 0.5, py + 0.5, vp)
            xs[py, px] = wx
            ys[py, px] = wy
    geom_occ = contains_xy(resolved, xs.ravel(), ys.ravel()).reshape(size, size)

    agreement = float(np.mean(geom_occ == raster_occ))
    assert agreement >= 0.99, f"geometry/raster agreement {agreement:.4f} < 0.99"
