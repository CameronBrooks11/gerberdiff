# gerberdiff

Diff tool for Gerber/Excellon PCB design files, with two complementary
engines:

- **Raster diff** (`diff`) -- renders both revisions with Cairo and XORs the
  pixels; produces visual overlay PNGs of changed regions.
- **Geometry diff** (`geomdiff`) -- computes resolution-independent,
  **attributed** changes on the parsed vector geometry: every change is
  classified as `added`, `removed`, `moved` (with dx/dy displacement, down
  to micrometres), or `resized`, with net names propagated from `%TO.N%`
  attributes.

The raster engine answers "*where* did pixels change?"; the geometry engine
answers "*what* changed, and by how much?". A $0.14\,\text{mm}$ component
move that renders as an unreadable field of XOR crescents in a raster diff
is reported by the geometry engine as "46 objects moved by
$(-0.139, -0.054)\,\text{mm}$".

## Install

```sh
pip install gerberdiff
```

Requires Python >= 3.11. The raster engine needs the system Cairo library
(`libcairo2` on Debian/Ubuntu, `cairo` via Homebrew); the geometry engine
and the parsers are Cairo-free and work everywhere.

## Quick start

```sh
# Geometry diff: what moved, resized, was added or removed -- and by how much
gerberdiff geomdiff before/ after/ --out-json report.json --out-svg overlays/

# Raster diff: visual overlay PNGs
gerberdiff diff before/ after/ --out-json report.json --out-png diffs/

# Exit 1 if any changes detected (useful in CI)
gerberdiff geomdiff before/ after/ --fail-on-diff
```

```python
import gerberdiff
from pathlib import Path

result = gerberdiff.compute_geometry_diff(Path("before/"), Path("after/"))
for layer in result.layers:
    for change in layer.changes:
        print(f"{layer.name}: {change.kind} {change.op_kind} "
              f"dx={change.dx_mm} dy={change.dy_mm}")
```

## Where to go next

| I want to... | Read |
| --- | --- |
| Use the command line | [CLI reference](cli.md) |
| Call it from Python | [Python API](api.md) |
| Parse the JSON reports | [JSON report schemas](schema.md) |
| Understand how it works | [Architecture](architecture.md) |
| Deep-dive the geometry engine | [Geometry diff engine](geometry-diff.md) |
| Browse the API surface | [API reference](reference/package.md) |
| Contribute | [Contributing](contributing.md) |

## Known limitations

- **Excellon rout mode:** only drill hits are processed; routing paths
  produce a `Warning` diagnostic but no geometry.
- **Deprecated RS-274X commands (`%MI%`, `%OF%`, `%SF%`, `%AS%`):** ignored
  with an `Info` diagnostic.
- **Rectangle/obround aperture strokes:** the raster engine strokes with
  `max(width, height)`; the geometry engine computes the exact Minkowski sum
  for linear strokes (see [Geometry diff engine](geometry-diff.md)).

## License

[Apache-2.0](https://github.com/CameronBrooks11/gerberdiff/blob/main/LICENSE).
