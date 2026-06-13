"""Export a geometry diff overlay as an SVG (Cairo-free).

Colour semantics:

- **red** -- removed material (before-state of ``removed`` changes)
- **green** -- added material (after-state of ``added`` changes)
- **blue** -- ``moved`` objects: after-state fill plus a displacement line
  from the before-centroid to the after-centroid
- **orange** -- ``resized`` objects: after-state fill, before-state outline

Y axis is flipped (Gerber +Y up -> SVG +Y down).  Polygon interiors (holes)
are preserved via even-odd fill paths.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from gerberdiff.geometry.types import GeometryChange, LayerGeometryDiff

_Sx = Callable[[float], float]

_COLOR_REMOVED = "#cc0000"
_COLOR_ADDED = "#00aa00"
_COLOR_MOVED = "#0066cc"
_COLOR_RESIZED = "#cc6600"

_FILL_OPACITY = 0.85
_PAD_FRACTION = 0.05


def write_geometry_svg(
    layer: LayerGeometryDiff,
    output_path: Path,
    *,
    canvas_px: int = 1600,
    overwrite: bool = False,
) -> None:
    """Write an SVG overlay of *layer*'s changes to *output_path*.

    Raises
    ------
    FileExistsError
        If *output_path* already exists and *overwrite* is ``False``.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output file already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_geometry_svg(layer, canvas_px=canvas_px), encoding="utf-8")


def render_geometry_svg(layer: LayerGeometryDiff, *, canvas_px: int = 1600) -> str:
    """Render *layer*'s changes to an SVG document string."""
    geoms: list[BaseGeometry] = []
    for c in layer.changes:
        if c.before_geom is not None:
            geoms.append(c.before_geom)
        if c.after_geom is not None:
            geoms.append(c.after_geom)

    if not geoms:
        return (
            "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'>"
            f"<title>{_escape(layer.name)}: no changes</title></svg>"
        )

    min_x = min(g.bounds[0] for g in geoms)
    min_y = min(g.bounds[1] for g in geoms)
    max_x = max(g.bounds[2] for g in geoms)
    max_y = max(g.bounds[3] for g in geoms)
    span = max(max_x - min_x, max_y - min_y, 1e-6)
    pad = span * _PAD_FRACTION
    min_x -= pad
    min_y -= pad
    max_x += pad
    max_y += pad

    scale = canvas_px / max(max_x - min_x, max_y - min_y)
    width = (max_x - min_x) * scale
    height = (max_y - min_y) * scale

    def sx(x: float) -> float:
        return (x - min_x) * scale

    def sy(y: float) -> float:  # Gerber +Y up -> SVG +Y down
        return (max_y - y) * scale

    parts: list[str] = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width:.0f}' "
        f"height='{height:.0f}' viewBox='0 0 {width:.0f} {height:.0f}'>",
        f"<title>{_escape(layer.name)}</title>",
        f"<rect width='{width:.0f}' height='{height:.0f}' fill='white'/>",
    ]
    for c in layer.changes:
        parts.extend(_change_svg(c, sx, sy))
    parts.append(_legend())
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _change_svg(c: GeometryChange, sx: _Sx, sy: _Sx) -> list[str]:
    parts: list[str] = []
    if c.kind == "removed" and c.before_geom is not None:
        parts.append(_geom_path(c.before_geom, _COLOR_REMOVED, _FILL_OPACITY, sx, sy))
    elif c.kind == "added" and c.after_geom is not None:
        parts.append(_geom_path(c.after_geom, _COLOR_ADDED, _FILL_OPACITY, sx, sy))
    elif c.kind == "moved" and c.after_geom is not None:
        parts.append(_geom_path(c.after_geom, _COLOR_MOVED, _FILL_OPACITY, sx, sy))
        if c.before_geom is not None:
            bc = c.before_geom.centroid
            ac = c.after_geom.centroid
            parts.append(
                f"<line x1='{sx(bc.x):.1f}' y1='{sy(bc.y):.1f}' "
                f"x2='{sx(ac.x):.1f}' y2='{sy(ac.y):.1f}' "
                f"stroke='{_COLOR_MOVED}' stroke-width='1.5'/>"
            )
    elif c.kind == "resized":
        if c.after_geom is not None:
            parts.append(_geom_path(c.after_geom, _COLOR_RESIZED, _FILL_OPACITY, sx, sy))
        if c.before_geom is not None:
            parts.append(_geom_path(c.before_geom, "none", 0.0, sx, sy, stroke=_COLOR_RESIZED))
    return [p for p in parts if p]


def _geom_path(
    geom: BaseGeometry,
    fill: str,
    opacity: float,
    sx: _Sx,
    sy: _Sx,
    stroke: str | None = None,
) -> str:
    """One even-odd <path> for all polygon rings (exteriors + holes)."""
    polys: list[Polygon]
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]

    d_parts: list[str] = []
    for poly in polys:
        if poly.is_empty:
            continue
        rings = [poly.exterior, *poly.interiors]
        for ring in rings:
            coords = " L ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in ring.coords)
            d_parts.append(f"M {coords} Z")
    if not d_parts:
        return ""
    stroke_attr = f" stroke='{stroke}' stroke-width='1'" if stroke else " stroke='none'"
    return (
        f"<path d='{' '.join(d_parts)}' fill='{fill}' fill-opacity='{opacity}' "
        f"fill-rule='evenodd'{stroke_attr}/>"
    )


def _legend() -> str:
    rows = [
        (_COLOR_REMOVED, "removed"),
        (_COLOR_ADDED, "added"),
        (_COLOR_MOVED, "moved"),
        (_COLOR_RESIZED, "resized"),
    ]
    items = [
        "<g font-family='sans-serif' font-size='16'>",
        "<rect x='8' y='8' width='120' height='98' fill='white' stroke='#888'/>",
    ]
    for i, (color, label) in enumerate(rows):
        y = 30 + i * 22
        items.append(f"<text x='20' y='{y}' fill='{color}'>{label}</text>")
    items.append("</g>")
    return "".join(items)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
