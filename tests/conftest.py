"""Shared pytest configuration.

When the native cairo library is unavailable (e.g. a bare Windows
environment), the raster-engine test modules are excluded from collection
-- importing them (or running them) would fail with ``OSError`` from
``cairocffi``.  The parse, diff-matching, and geometry test suites are
Cairo-free and always run.
"""

from __future__ import annotations

from tests.cairo_support import HAS_CAIRO

collect_ignore: list[str] = []

if not HAS_CAIRO:
    collect_ignore += [
        # Direct raster-engine tests (import or call cairocffi).
        "test_renderer.py",
        "test_draw_ops.py",
        "test_macro_renderer.py",
        "test_png_export.py",
        "test_block_aperture.py",
        # Pixel-diff engine and CLI commands that rasterise at runtime.
        "test_diff_engine.py",
        "test_cli_diff.py",
        "test_cli_render.py",
    ]
