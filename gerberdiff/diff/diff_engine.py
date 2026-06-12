"""Pixel-based diff engine: render two ParsedImages, XOR pixel buffers, CCL.

Pipeline
--------
1. ``compute_diff`` renders both images to the same viewport and XORs the
   RGB channels to find changed pixels.
2. ``_ccl_and_extract`` uses ``scipy.ndimage.label`` (4-connectivity) to
   identify contiguous changed regions and converts pixel coordinates to
   world coordinates via ``screen_to_world``.
3. ``merge_overlapping_regions`` iteratively merges regions whose bounding
   boxes overlap within a tolerance, then re-sorts and re-numbers them.

Coordinate convention
---------------------
All region coordinates (centroid, bounding box) are in **inches**, matching
the ``ParsedImage`` IR convention.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from pathlib import Path

import numpy as np
from scipy.ndimage import center_of_mass, find_objects
from scipy.ndimage import label as ndimage_label

from gerberdiff.render.viewport import (
    Viewport,
    compute_viewport,
    merge_bounding_boxes,
    screen_to_world,
)
from gerberdiff.types import (
    BoundingBox,
    Diagnostic,
    DiagnosticSeverity,
    DiffResult,
    GerberParseError,
    LayerDiffResult,
    LayerStatus,
    ParsedImage,
    Region,
)

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SingleLayerDiff:
    """Full output of a single-layer pixel diff."""

    regions: list[Region]
    viewport: Viewport
    changed_pixel_count: int
    total_pixel_count: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_diff(
    image_a: ParsedImage,
    image_b: ParsedImage,
    width: int,
    height: int,
    alignment_offset: tuple[float, float] | None = None,
    min_pixel_count: int = 4,
    merge_tolerance: float = 0.05,
    overlay_callback: Callable[[np.ndarray, np.ndarray, np.ndarray], None] | None = None,
) -> SingleLayerDiff:
    """Render both images to a shared viewport and compute the pixel diff.

    Parameters
    ----------
    image_a, image_b:
        Parsed Gerber/Excellon images to compare.
    width, height:
        Canvas dimensions in pixels.
    alignment_offset:
        Optional ``(dx, dy)`` inches translation applied to *image_b* before
        rendering.  Used when the two board revisions have different origins.
    min_pixel_count:
        Minimum pixel count for a region to be reported (filters noise).
    merge_tolerance:
        Bounding-box padding (inches) used when deciding whether to merge two
        nearby regions into one.
    overlay_callback:
        Optional callable invoked with ``(arr_a, arr_b, xor)`` before the
        arrays are released.  Use this to write a PNG overlay without keeping
        all three ``(H, W, 4)`` arrays live simultaneously.
    """
    # Lazy import: keeps `import gerberdiff` (and the Cairo-free geometry
    # pipeline) working on systems without the native cairo library.
    from gerberdiff.render.renderer import render_to_numpy

    bbox = merge_bounding_boxes(image_a.bounding_box, image_b.bounding_box)
    vp = compute_viewport(bbox, width, height)

    arr_a = render_to_numpy(image_a, vp)
    arr_b = render_to_numpy(image_b, vp, coordinate_offset=alignment_offset)

    xor = np.bitwise_xor(arr_a, arr_b)
    # Changed wherever any of the three colour channels differs (ignore alpha).
    mask: np.ndarray = np.any(xor[..., :3] > 0, axis=-1)

    regions = _ccl_and_extract(mask, vp, min_pixel_count)
    regions = merge_overlapping_regions(regions, tolerance=merge_tolerance)

    if overlay_callback is not None:
        overlay_callback(arr_a, arr_b, xor)

    return SingleLayerDiff(
        regions=regions,
        viewport=vp,
        changed_pixel_count=int(mask.sum()),
        total_pixel_count=width * height,
    )


def compute_full_diff(
    before_dir: Path,
    after_dir: Path,
    *,
    width: int = 2048,
    height: int = 2048,
    layers: Sequence[str] | None = None,
    alignment_offset: tuple[float, float] | None = None,
    min_pixel_count: int = 4,
    merge_tolerance: float = 0.05,
    overlay_callback: Callable[[str, np.ndarray, np.ndarray, np.ndarray], None] | None = None,
    on_diagnostic: Callable[[Path, Diagnostic], None] | None = None,
) -> DiffResult:
    """Diff two directories of Gerber/Excellon layer files.

    Parameters
    ----------
    before_dir, after_dir:
        Directories containing the before and after layer files.
    width, height:
        Canvas dimensions in pixels.
    layers:
        If given, only layers whose names appear in this sequence are diffed.
    alignment_offset:
        Optional ``(dx, dy)`` inch translation applied to *after_dir* images
        before diffing.
    min_pixel_count:
        Minimum pixel count for a region to be reported.
    merge_tolerance:
        Bounding-box padding (inches) used when merging nearby regions.
    overlay_callback:
        Called with ``(layer_name, arr_a, arr_b, xor)`` for each matched
        layer.  Use this to write per-layer overlay PNGs without keeping all
        arrays live simultaneously.
    on_diagnostic:
        Called with ``(path, diagnostic)`` for every non-fatal diagnostic
        (``Warning`` and ``Info`` severity) encountered while parsing.

    Raises
    ------
    GerberParseError
        When a file contains a fatal (``Error``-severity) parse diagnostic.
    OSError
        When a layer file cannot be read.
    """
    # Lazy imports: keep parse/ and diff/layer_matcher out of the module-load
    # critical path for callers that only use compute_diff.
    from gerberdiff.diff.layer_matcher import EXCELLON_SUFFIXES, match_layers
    from gerberdiff.parse.excellon_parser import parse_excellon
    from gerberdiff.parse.gerber_state import parse_gerber

    def _parse(path: Path) -> ParsedImage:
        content = path.read_text(errors="replace")
        if path.suffix.lower() in EXCELLON_SUFFIXES:
            img = parse_excellon(content, source_path=path)
        else:
            img = parse_gerber(content, source_path=path)
        for diag in img.diagnostics:
            if diag.severity == DiagnosticSeverity.Error:
                raise GerberParseError(path, diag.message, diag.line)
            if on_diagnostic is not None:
                on_diagnostic(path, diag)
        return img

    pairs = match_layers(before_dir, after_dir)
    if layers is not None:
        pairs = [p for p in pairs if p.name in layers]

    layer_results: list[LayerDiffResult] = []

    for pair in pairs:
        total_px = width * height

        if pair.status in (LayerStatus.Added, LayerStatus.Removed):
            src_path = pair.after_path if pair.status == LayerStatus.Added else pair.before_path
            assert src_path is not None  # invariant guaranteed by match_layers
            _parse(src_path)  # validate file and surface diagnostics
            lr = LayerDiffResult(
                name=pair.name,
                status=pair.status,
                layer_type=pair.layer_type,
                changed_pixel_count=total_px,
                total_pixel_count=total_px,
                regions=[],
            )
        else:
            assert pair.before_path is not None and pair.after_path is not None
            img_a = _parse(pair.before_path)
            img_b = _parse(pair.after_path)

            layer_ov_cb: Callable[[np.ndarray, np.ndarray, np.ndarray], None] | None = None
            if overlay_callback is not None:
                name = pair.name

                def _wrap(
                    a: np.ndarray,
                    b: np.ndarray,
                    x: np.ndarray,
                    _n: str = name,
                ) -> None:
                    overlay_callback(_n, a, b, x)

                layer_ov_cb = _wrap

            result = compute_diff(
                img_a,
                img_b,
                width=width,
                height=height,
                alignment_offset=alignment_offset,
                min_pixel_count=min_pixel_count,
                merge_tolerance=merge_tolerance,
                overlay_callback=layer_ov_cb,
            )
            lr = LayerDiffResult(
                name=pair.name,
                status=LayerStatus.Matched,
                layer_type=pair.layer_type,
                changed_pixel_count=result.changed_pixel_count,
                total_pixel_count=result.total_pixel_count,
                regions=result.regions,
            )

        layer_results.append(lr)

    return DiffResult(layers=layer_results)


# ---------------------------------------------------------------------------
# Region merge helpers (public so layer_matcher / CLI can call them)
# ---------------------------------------------------------------------------


def boxes_overlap(a: BoundingBox, b: BoundingBox, tolerance: float) -> bool:
    """Return True if box *a* and box *b* overlap when each is padded by
    *tolerance* on every side."""
    if a.max_x + tolerance < b.min_x - tolerance:
        return False
    if b.max_x + tolerance < a.min_x - tolerance:
        return False
    if a.max_y + tolerance < b.min_y - tolerance:
        return False
    if b.max_y + tolerance < a.min_y - tolerance:
        return False
    return True


def merge_overlapping_regions(
    regions: list[Region],
    tolerance: float = 0.05,
) -> list[Region]:
    """Iteratively merge regions whose bounding boxes overlap (within
    *tolerance*), then sort and re-number.

    The sort key matches the reference: descending ``centroid_y``, then
    ascending ``centroid_x`` (top-of-board changes first).
    """
    if len(regions) <= 1:
        return regions

    working = list(regions)
    changed = True

    while changed:
        changed = False
        merged: list[Region] = []
        absorbed: set[int] = set()

        for i in range(len(working)):
            if i in absorbed:
                continue
            current = working[i]
            retry = True
            while retry:
                retry = False
                for j in range(i + 1, len(working)):
                    if j in absorbed:
                        continue
                    if boxes_overlap(current.bounding_box, working[j].bounding_box, tolerance):
                        current = _merge_region_pair(current, working[j])
                        absorbed.add(j)
                        retry = True
                        changed = True
            merged.append(current)
        working = merged

    # Sort: descending centroid_y (higher Y = closer to top in Gerber coords),
    # then ascending centroid_x to break ties.
    working.sort(key=lambda r: (-r.centroid_y, r.centroid_x))

    # Re-number ids 1..n after sort.
    return [dc_replace(r, id=i + 1) for i, r in enumerate(working)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ccl_and_extract(
    mask: np.ndarray,
    vp: Viewport,
    min_pixel_count: int,
) -> list[Region]:
    """Run 4-connected CCL on *mask* and return world-space regions.

    Uses ``scipy.ndimage.label`` (default cross structure = 4-connectivity,
    matching the reference union-find implementation) and collects per-label
    bounding boxes and centroids via ``find_objects`` / ``center_of_mass``.
    """
    labeled_arr, num_features = ndimage_label(mask)
    if num_features == 0:
        return []

    # Per-label bounding slices -- O(H*W) single pass.
    obj_slices = find_objects(labeled_arr)

    # center_of_mass with a list index always returns list[tuple[float, ...]].
    label_ids = list(range(1, num_features + 1))
    centroids_list = center_of_mass(mask, labeled_arr, label_ids)

    regions: list[Region] = []
    region_id = 1

    for idx, (obj_slice, centroid_rc) in enumerate(zip(obj_slices, centroids_list, strict=True)):
        if obj_slice is None:
            continue
        lbl = idx + 1
        sub = labeled_arr[obj_slice] == lbl
        count = int(sub.sum())
        if count < min_pixel_count:
            continue

        # Bounding box corners in pixel coords.
        row_min = obj_slice[0].start
        row_max = obj_slice[0].stop - 1
        col_min = obj_slice[1].start
        col_max = obj_slice[1].stop - 1

        # screen_to_world(px=col, py=row, vp) -- note col is x, row is y.
        x0, y0 = screen_to_world(col_min, row_min, vp)
        x1, y1 = screen_to_world(col_max, row_max, vp)

        bb = BoundingBox(
            min_x=min(x0, x1),
            min_y=min(y0, y1),
            max_x=max(x0, x1),
            max_y=max(y0, y1),
        )

        cx, cy = screen_to_world(centroid_rc[1], centroid_rc[0], vp)

        regions.append(
            Region(
                id=region_id,
                centroid_x=cx,
                centroid_y=cy,
                bounding_box=bb,
                pixel_count=count,
            )
        )
        region_id += 1

    # Initial sort by descending pixel count (largest changes first, before merge).
    regions.sort(key=lambda r: -r.pixel_count)
    return regions


def _merge_region_pair(a: Region, b: Region) -> Region:
    """Return a new Region that is the weighted merge of *a* and *b*."""
    total = a.pixel_count + b.pixel_count
    return Region(
        id=a.id,
        centroid_x=(a.centroid_x * a.pixel_count + b.centroid_x * b.pixel_count) / total,
        centroid_y=(a.centroid_y * a.pixel_count + b.centroid_y * b.pixel_count) / total,
        bounding_box=BoundingBox(
            min_x=min(a.bounding_box.min_x, b.bounding_box.min_x),
            min_y=min(a.bounding_box.min_y, b.bounding_box.min_y),
            max_x=max(a.bounding_box.max_x, b.bounding_box.max_x),
            max_y=max(a.bounding_box.max_y, b.bounding_box.max_y),
        ),
        pixel_count=total,
    )
