# gerberdiff

[![CI](https://github.com/CameronBrooks11/gerberdiff/actions/workflows/ci.yml/badge.svg)](https://github.com/CameronBrooks11/gerberdiff/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gerberdiff)](https://pypi.org/project/gerberdiff/)
[![Python](https://img.shields.io/pypi/pyversions/gerberdiff)](https://pypi.org/project/gerberdiff/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Diff tool for Gerber/Excellon PCB design files, with two complementary
engines:

- **Raster diff** (`diff`) -- visual overlay PNGs of changed pixels.
- **Geometry diff** (`geomdiff`) -- resolution-independent, attributed
  changes (`moved` / `resized` / `added` / `removed`) computed on the
  parsed vector geometry, down to micrometre displacements.

## Install

```sh
pip install gerberdiff
```

Requires Python >= 3.11. The raster engine needs the system Cairo library
(`libcairo2` on Debian/Ubuntu, `cairo` via Homebrew); the geometry engine
is Cairo-free.

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

## Docs

| Topic                | File                                         |
| -------------------- | -------------------------------------------- |
| CLI reference        | [docs/cli.md](docs/cli.md)                   |
| Python API           | [docs/api.md](docs/api.md)                   |
| JSON report schemas  | [docs/schema.md](docs/schema.md)             |
| Architecture         | [docs/architecture.md](docs/architecture.md) |
| Geometry diff engine | [docs/geometry-diff.md](docs/geometry-diff.md) |

## Known limitations

- **Excellon rout mode:** only drill hits are processed; routing paths produce a
  `Warning` diagnostic but no geometry.
- **Deprecated RS-274X commands (`%MI%`, `%OF%`, `%SF%`, `%AS%`):** ignored with an
  `Info` diagnostic.
- **Rectangle/obround aperture strokes:** the raster engine strokes with
  `max(width, height)`; the geometry engine computes the exact Minkowski sum
  for linear strokes (see [docs/geometry-diff.md](docs/geometry-diff.md)).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).
