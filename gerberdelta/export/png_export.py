"""Export a diff overlay PNG using cairocffi surfaces and numpy.

Colour scheme
-------------
- **Red:**   pixels present in image A but not B (geometry removed)
- **Green:** pixels present in image B but not A (geometry added)
- **Grey:**  unchanged geometry from image A (only when *show_common=True*)
- **Black:** background (fully transparent in ARGB32)
"""

from __future__ import annotations

from pathlib import Path

import cairocffi as cairo
import numpy as np

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_overlay_png(
    arr_a: np.ndarray,
    arr_b: np.ndarray,
    xor: np.ndarray,
    output_path: Path,
    show_common: bool = False,
    overwrite: bool = False,
) -> None:
    """Composite a red/green diff overlay and write it to *output_path*.

    Parameters
    ----------
    arr_a:
        Rendered image A, shape ``(H, W, 4)`` uint8 BGRA (Cairo ARGB32 LE).
    arr_b:
        Rendered image B, shape ``(H, W, 4)`` uint8.
    xor:
        Channel-wise XOR of *arr_a* and *arr_b* (from ``SingleLayerDiff.xor``).
    output_path:
        Destination PNG file path.  Parent directories are created if needed.
    show_common:
        When ``True``, unchanged geometry (present in both A and B) is drawn
        in grey (128, 128, 128) in the output image.
    overwrite:
        When ``False`` (default), raises ``FileExistsError`` if *output_path*
        already exists.

    Raises
    ------
    FileExistsError
        If *output_path* exists and *overwrite* is ``False``.
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output file already exists: {output_path}")

    height, width = arr_a.shape[:2]

    # --- build boolean masks ------------------------------------------------
    # Changed wherever any of the first three channels of XOR is non-zero.
    xor_mask: np.ndarray = np.any(xor[..., :3] > 0, axis=-1)

    # Alpha channels: pixel is "lit" in A or B when alpha > 0.
    alpha_a: np.ndarray = arr_a[..., 3] > 0
    alpha_b: np.ndarray = arr_b[..., 3] > 0

    removed = xor_mask & alpha_a & ~alpha_b  # in A, not in B
    added = xor_mask & alpha_b & ~alpha_a  # in B, not in A
    if show_common:
        common = alpha_a & alpha_b & ~xor_mask

    # --- build BGRA output buffer -------------------------------------------
    out = np.zeros((height, width, 4), dtype=np.uint8)

    # Removed -> red   (B=0, G=0, R=255, A=255  ->  BGRA: [0, 0, 255, 255])
    out[removed] = [0, 0, 255, 255]
    # Added   -> green (B=0, G=255, R=0, A=255  ->  BGRA: [0, 255, 0, 255])
    out[added] = [0, 255, 0, 255]
    if show_common:
        out[common] = [128, 128, 128, 255]

    # --- write via cairocffi ImageSurface -----------------------------------
    surface = cairo.ImageSurface.create_for_data(
        out,
        cairo.FORMAT_ARGB32,
        width,
        height,
        width * 4,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(output_path))
