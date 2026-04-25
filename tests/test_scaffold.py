"""Smoke tests for package import and CLI wiring."""
from __future__ import annotations


def test_version_string_is_defined() -> None:
    import gerberdelta
    assert hasattr(gerberdelta, "__version__")
    assert isinstance(gerberdelta.__version__, str)
    assert gerberdelta.__version__ == "0.1.0"


def test_cli_group_importable() -> None:
    from gerberdelta.cli import cli
    assert callable(cli)
