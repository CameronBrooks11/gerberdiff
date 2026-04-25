from __future__ import annotations

import click

from gerberdelta import __version__


@click.group()
@click.version_option(__version__, prog_name="gerberdelta")
def cli() -> None:
    """Geometry-aware Gerber/Excellon diff tool."""


if __name__ == "__main__":
    cli()
