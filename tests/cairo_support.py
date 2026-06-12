"""Detect whether the native cairo library is available.

``cairocffi`` raises ``OSError`` (not ``ImportError``) when the system
cairo shared library is missing, so ``pytest.importorskip`` cannot be used.
Raster-engine tests are skipped on systems without cairo (see
``conftest.py``); the parse and geometry pipelines are Cairo-free and their
tests always run.
"""

from __future__ import annotations


def _cairo_available() -> bool:
    try:
        import cairocffi  # noqa: F401
    except (OSError, ImportError):
        return False
    return True


HAS_CAIRO = _cairo_available()
CAIRO_SKIP_REASON = "native cairo library not available (raster engine only)"
