from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from gerberdelta import __version__
from gerberdelta.types import DiagnosticSeverity

_EXCELLON_SUFFIXES = frozenset({".drl", ".exc", ".xln", ".ncd"})


@click.group()
@click.version_option(__version__, prog_name="gerberdelta")
def cli() -> None:
    """Geometry-aware Gerber/Excellon diff tool."""


@cli.command("parse")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dump-ir", is_flag=True, help="Print ParsedImage summary as JSON to stdout.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress all output except errors.")
@click.option("-v", "--verbose", is_flag=True, help="Print Info-level diagnostics.")
def parse_cmd(file: Path, dump_ir: bool, quiet: bool, verbose: bool) -> None:
    """Parse a Gerber or Excellon file and report diagnostics."""
    from gerberdelta.parse.excellon_parser import parse_excellon
    from gerberdelta.parse.gerber_state import parse_gerber

    try:
        content = file.read_text(errors="replace")
    except OSError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    if file.suffix.lower() in _EXCELLON_SUFFIXES:
        img = parse_excellon(content, source_path=file)
    else:
        img = parse_gerber(content, source_path=file)

    has_errors = False
    for diag in img.diagnostics:
        loc = f" (line {diag.line})" if diag.line else ""
        if diag.severity == DiagnosticSeverity.Error:
            has_errors = True
            click.echo(f"error: {diag.message}{loc}", err=True)
        elif diag.severity == DiagnosticSeverity.Warning and not quiet:
            click.echo(f"warning: {diag.message}{loc}", err=True)
        elif diag.severity == DiagnosticSeverity.Info and verbose:
            click.echo(f"info: {diag.message}", err=True)

    if not quiet and not dump_ir:
        click.echo(f"nets: {len(img.nets)}")
        click.echo(f"apertures: {len(img.apertures)}")
        if img.bounding_box.is_valid:
            bb = img.bounding_box
            click.echo(
                f"bbox: x=[{bb.min_x:.6f}, {bb.max_x:.6f}]"
                f" y=[{bb.min_y:.6f}, {bb.max_y:.6f}] inches"
            )
        else:
            click.echo("bbox: empty (no geometry)")

    if dump_ir:
        bb = img.bounding_box
        ir: dict[str, object] = {
            "source": str(file),
            "net_count": len(img.nets),
            "aperture_count": len(img.apertures),
            "layer_count": len(img.layers),
            "bounding_box": {
                "min_x": bb.min_x if bb.is_valid else None,
                "min_y": bb.min_y if bb.is_valid else None,
                "max_x": bb.max_x if bb.is_valid else None,
                "max_y": bb.max_y if bb.is_valid else None,
            },
            "diagnostics": [
                {"severity": d.severity.value, "message": d.message, "line": d.line}
                for d in img.diagnostics
            ],
        }
        click.echo(json.dumps(ir, indent=2))

    sys.exit(2 if has_errors else 0)


if __name__ == "__main__":
    cli()
