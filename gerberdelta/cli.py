from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

from gerberdelta import __version__
from gerberdelta.types import DiagnosticSeverity, LayerStatus

_EXCELLON_SUFFIXES = frozenset({".drl", ".exc", ".xln", ".ncd"})
_MEMORY_WARN_PIXELS = 16_777_216  # 4096^2


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
        click.echo(f"nets: {len(img.draw_ops)}")
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
            "net_count": len(img.draw_ops),
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


@cli.command("render")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out-png",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output PNG path.",
)
@click.option("--width", default=2048, show_default=True, help="Canvas width in pixels.")
@click.option("--height", default=2048, show_default=True, help="Canvas height in pixels.")
@click.option("--overwrite", is_flag=True, help="Overwrite output file if it already exists.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress all output except errors.")
@click.option("-v", "--verbose", is_flag=True, help="Print render timing and diagnostic detail.")
def render_cmd(
    file: Path,
    out_png: Path,
    width: int,
    height: int,
    overwrite: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Render a Gerber or Excellon file to a PNG image."""
    from gerberdelta.parse.excellon_parser import parse_excellon
    from gerberdelta.parse.gerber_state import parse_gerber
    from gerberdelta.render.renderer import render_to_surface
    from gerberdelta.render.viewport import compute_viewport

    # Memory warning -- non-blocking.
    total_pixels = width * height
    if total_pixels > _MEMORY_WARN_PIXELS:
        mb = (total_pixels * 4) / (1024 * 1024)
        click.echo(
            f"warning: canvas {width}x{height} = {total_pixels:,} pixels "
            f"(~{mb:.0f} MB); reduce --width/--height if memory is limited.",
            err=True,
        )

    if out_png.exists() and not overwrite:
        click.echo(
            f"error: output file already exists: {out_png}  (use --overwrite to replace)",
            err=True,
        )
        sys.exit(1)

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

    if has_errors:
        sys.exit(2)

    vp = compute_viewport(img.bounding_box, width, height)

    t0 = time.perf_counter()
    surface = render_to_surface(img, vp)
    elapsed = time.perf_counter() - t0

    try:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        surface.write_to_png(str(out_png))
    except OSError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    if not quiet:
        click.echo(f"rendered {width}x{height} -> {out_png}")
    if verbose:
        click.echo(f"render time: {elapsed * 1000:.1f} ms")
        click.echo(f"nets: {len(img.draw_ops)}  apertures: {len(img.apertures)}")


# ---------------------------------------------------------------------------
# diff subcommand
# ---------------------------------------------------------------------------


@cli.command("diff")
@click.argument("before_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("after_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--layer",
    "layers",
    multiple=True,
    help="Restrict diff to this layer name (repeatable).",
)
@click.option("--width", default=2048, show_default=True, help="Canvas width in pixels.")
@click.option("--height", default=2048, show_default=True, help="Canvas height in pixels.")
@click.option(
    "--min-pixels",
    default=4,
    show_default=True,
    help="Minimum changed-pixel count to report a region.",
)
@click.option(
    "--merge-tolerance", default=0.05, show_default=True, help="Region merge padding in inches."
)
@click.option(
    "--out-json",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write JSON report to this file.",
)
@click.option(
    "--out-png",
    "out_png_dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Write diff overlay PNG(s) to this directory.",
)
@click.option("--overwrite", is_flag=True, help="Allow overwriting existing output files.")
@click.option(
    "--png-show-common", is_flag=True, help="Include unchanged geometry as grey in PNG overlay."
)
@click.option(
    "--align-offset",
    default="0,0",
    show_default=True,
    help="Translate image B by X,Y inches before diffing (e.g. '0.5,0').",
)
@click.option("--fail-on-diff", is_flag=True, help="Exit with code 1 if any changes are detected.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress all output except errors.")
@click.option("-v", "--verbose", is_flag=True, help="Print per-layer and per-region detail.")
def diff_cmd(
    before_dir: Path,
    after_dir: Path,
    layers: tuple[str, ...],
    width: int,
    height: int,
    min_pixels: int,
    merge_tolerance: float,
    out_json: Path | None,
    out_png_dir: Path | None,
    overwrite: bool,
    png_show_common: bool,
    align_offset: str,
    fail_on_diff: bool,
    quiet: bool,
    verbose: bool,
) -> None:
    """Compare two directories of Gerber/Excellon layer files."""
    import time

    from gerberdelta.diff.diff_engine import compute_diff
    from gerberdelta.diff.layer_matcher import match_layers
    from gerberdelta.export.json_report import write_report
    from gerberdelta.export.png_export import build_overlay_png
    from gerberdelta.parse.excellon_parser import parse_excellon
    from gerberdelta.parse.gerber_state import parse_gerber
    from gerberdelta.types import DiffResult, LayerDiffResult, ParsedImage

    # Parse --align-offset
    try:
        ox_str, oy_str = align_offset.split(",", 1)
        alignment_offset: tuple[float, float] | None = (float(ox_str), float(oy_str))
        if alignment_offset == (0.0, 0.0):
            alignment_offset = None
    except ValueError:
        click.echo(
            "error: --align-offset must be two comma-separated floats (e.g. '0.5,0')", err=True
        )
        sys.exit(2)

    # Memory warning
    total_pixels = width * height
    if total_pixels > _MEMORY_WARN_PIXELS and not quiet:
        mb = (total_pixels * 4) / (1024 * 1024)
        click.echo(
            f"warning: canvas {width}x{height} = {total_pixels:,} pixels (~{mb:.0f} MB)",
            err=True,
        )

    # Match layers
    pairs = match_layers(before_dir, after_dir)
    if layers:
        pairs = [p for p in pairs if p.name in layers]

    layer_results: list[LayerDiffResult] = []
    t_start = time.perf_counter()

    for pair in pairs:
        t_layer = time.perf_counter()

        # Added / removed layers: report 100% changed without rendering both.
        if pair.status in (LayerStatus.Added, LayerStatus.Removed):
            src_path = pair.after_path if pair.status == LayerStatus.Added else pair.before_path
            if src_path is None:
                click.echo(
                    f"error: {pair.name}: {pair.status} layer has no associated path",
                    err=True,
                )
                sys.exit(2)
            try:
                content = src_path.read_text(errors="replace")
            except OSError as exc:
                click.echo(f"error: {exc}", err=True)
                sys.exit(1)
            if src_path.suffix.lower() in _EXCELLON_SUFFIXES:
                img = parse_excellon(content, source_path=src_path)
            else:
                img = parse_gerber(content, source_path=src_path)
            total_px = width * height
            lr = LayerDiffResult(
                name=pair.name,
                status=pair.status,
                layer_type=pair.layer_type,
                changed_pixel_count=total_px,
                total_pixel_count=total_px,
                regions=[],
            )
            layer_results.append(lr)
            if verbose:
                click.echo(f"  {pair.name}: {pair.status} (100% changed)")
            continue

        # Matched layers: full diff
        if pair.before_path is None or pair.after_path is None:
            click.echo(
                f"error: {pair.name}: matched layer is missing before or after path",
                err=True,
            )
            sys.exit(2)

        def _parse(path: Path) -> ParsedImage:
            try:
                content = path.read_text(errors="replace")
            except OSError as exc:
                click.echo(f"error: {exc}", err=True)
                sys.exit(1)
            if path.suffix.lower() in _EXCELLON_SUFFIXES:
                return parse_excellon(content, source_path=path)
            return parse_gerber(content, source_path=path)

        img_a = _parse(pair.before_path)
        img_b = _parse(pair.after_path)

        # Abort on parse errors.
        for img, path in ((img_a, pair.before_path), (img_b, pair.after_path)):
            for diag in img.diagnostics:
                loc = f" (line {diag.line})" if diag.line else ""
                if diag.severity == DiagnosticSeverity.Error:
                    click.echo(f"error: {path.name}: {diag.message}{loc}", err=True)
                    sys.exit(2)
                elif diag.severity == DiagnosticSeverity.Warning and not quiet:
                    click.echo(f"warning: {path.name}: {diag.message}{loc}", err=True)

        # PNG overlay per matched layer
        if out_png_dir is not None:
            png_path = out_png_dir / f"{pair.name}_diff.png"

            def _write_overlay(
                arr_a: object,
                arr_b: object,
                xor: object,
                _path: Path = png_path,
            ) -> None:
                import numpy as _np

                try:
                    build_overlay_png(
                        _np.asarray(arr_a),
                        _np.asarray(arr_b),
                        _np.asarray(xor),
                        _path,
                        show_common=png_show_common,
                        overwrite=overwrite,
                    )
                except FileExistsError as exc:
                    click.echo(f"error: {exc}  (use --overwrite to replace)", err=True)
                    sys.exit(1)

            overlay_cb = _write_overlay
        else:
            overlay_cb = None

        result = compute_diff(
            img_a,
            img_b,
            width=width,
            height=height,
            alignment_offset=alignment_offset,
            min_pixel_count=min_pixels,
            merge_tolerance=merge_tolerance,
            overlay_callback=overlay_cb,
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

        if verbose:
            elapsed_layer = time.perf_counter() - t_layer
            click.echo(
                f"  {pair.name}: {result.changed_pixel_count} changed px, "
                f"{len(result.regions)} regions  ({elapsed_layer * 1000:.0f} ms)"
            )
            for region in result.regions:
                click.echo(
                    f"    region {region.id}: {region.pixel_count} px  "
                    f"centroid=({region.centroid_x:.4f}, {region.centroid_y:.4f})"
                )

    # Build DiffResult
    has_changes = any(lr.changed_pixel_count > 0 or lr.status != LayerStatus.Matched for lr in layer_results)
    diff_result = DiffResult(layers=layer_results, has_changes=has_changes)

    # JSON report
    if out_json is not None:
        try:
            write_report(diff_result, out_json, overwrite=overwrite)
        except FileExistsError as exc:
            click.echo(f"error: {exc}  (use --overwrite to replace)", err=True)
            sys.exit(1)

    elapsed_total = time.perf_counter() - t_start

    # Terminal summary
    if not quiet:
        changed_layers = sum(
            1 for lr in layer_results if lr.changed_pixel_count > 0 or lr.status != LayerStatus.Matched
        )
        click.echo(
            f"diff: {changed_layers}/{len(layer_results)} layers changed  "
            f"({elapsed_total * 1000:.0f} ms)"
        )
        if out_json:
            click.echo(f"report: {out_json}")

    sys.exit(1 if fail_on_diff and has_changes else 0)


if __name__ == "__main__":
    cli()
