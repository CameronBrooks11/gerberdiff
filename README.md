# gerberdelta

[![CI](https://github.com/CameronBrooks11/gerberdelta/actions/workflows/ci.yml/badge.svg)](https://github.com/CameronBrooks11/gerberdelta/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gerberdelta)](https://pypi.org/project/gerberdelta/)
[![Python](https://img.shields.io/pypi/pyversions/gerberdelta)](https://pypi.org/project/gerberdelta/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Visual raster diff tool for Gerber/Excellon PCB design files -- compare two revisions of a PCB design and highlight what changed.

## Installation

```sh
pip install gerberdelta
# with optional rich terminal output:
pip install "gerberdelta[rich]"
```

Requires Python >= 3.11.

## CLI commands

### `parse` -- inspect a single file

```sh
gerberdelta parse board.gbr
gerberdelta parse board.gbr --dump-ir    # JSON summary to stdout
gerberdelta parse board.gbr --verbose    # include info-level diagnostics
```

### `render` -- rasterise a single file to PNG

```sh
gerberdelta render board.gbr --out-png board.png
gerberdelta render board.gbr --out-png board.png --width 4096 --height 4096
gerberdelta render board.gbr --out-png board.png --overwrite
```

### `diff` -- compare two layer directories

```sh
gerberdelta diff before/ after/
gerberdelta diff before/ after/ --fail-on-diff          # exit 1 if changes found
gerberdelta diff before/ after/ --out-json report.json  # machine-readable report
gerberdelta diff before/ after/ --out-png diff_pngs/    # one overlay PNG per layer
gerberdelta diff before/ after/ --layer F.Cu --verbose  # restrict to one layer
gerberdelta diff before/ after/ --align-offset 0.5,0    # shift board B by 0.5 in
```

#### diff options

| Option                  | Default | Description                               |
| ----------------------- | ------- | ----------------------------------------- |
| `--width` / `--height`  | 2048    | Canvas size in pixels                     |
| `--min-pixels`          | 4       | Minimum pixel count for a reported region |
| `--merge-tolerance`     | 0.05    | Region merge padding in inches            |
| `--layer NAME`          | (all)   | Restrict to named layer (repeatable)      |
| `--out-json PATH`       | (none)  | Write JSON diff report                    |
| `--out-png DIR`         | (none)  | Write per-layer overlay PNGs              |
| `--overwrite`           | false   | Allow overwriting existing output files   |
| `--png-show-common`     | false   | Shade unchanged geometry grey in PNGs     |
| `--align-offset X,Y`    | 0,0     | Translate board B before diffing (inches) |
| `--fail-on-diff`        | false   | Exit 1 if any changes detected            |
| `--quiet` / `--verbose` | (none)  | Suppress or expand terminal output        |

#### Overlay PNG colour scheme

| Colour | Meaning                                            |
| ------ | -------------------------------------------------- |
| Red    | Geometry present in **before** only (removed)      |
| Green  | Geometry present in **after** only (added)         |
| Yellow | Geometry changed (both non-zero, different value)  |
| Grey   | Unchanged geometry (only with `--png-show-common`) |

#### JSON report schema

```json
{
  "version": 1,
  "generator": "gerberdelta",
  "summary": {
    "changed_layers": 3,
    "total_regions": 12,
    "has_changes": true
  },
  "layers": [
    {
      "name": "A64-OlinuXino-F.Cu",
      "status": "matched",
      "layer_type": "FCu",
      "changed_pixel_count": 1402,
      "total_pixel_count": 4194304,
      "changed_fraction": 0.000334,
      "regions": [
        {
          "id": 1,
          "centroid_x": 1.234,
          "centroid_y": 0.987,
          "bbox": { "min_x": 1.21, "min_y": 0.97, "max_x": 1.26, "max_y": 1.0 },
          "pixel_count": 84
        }
      ]
    }
  ]
}
```

## Python API

```python
import gerberdelta

# Parse
img = gerberdelta.parse_gerber(Path("board.gbr").read_text())
img = gerberdelta.parse_excellon(Path("board.drl").read_text())

# Render to numpy array (H, W, 4) uint8 BGRA
from gerberdelta.render.viewport import compute_viewport
vp = compute_viewport(img.bounding_box, width=1024, height=1024)
arr = gerberdelta.render_to_numpy(img, vp)

# Diff two revisions
before = gerberdelta.parse_gerber(Path("before/F.Cu.gbr").read_text())
after  = gerberdelta.parse_gerber(Path("after/F.Cu.gbr").read_text())
diff = gerberdelta.compute_diff(before, after, width=1024, height=1024)
print(f"{diff.changed_pixel_count} changed pixels across {len(diff.regions)} regions")
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, test, and lint commands.
