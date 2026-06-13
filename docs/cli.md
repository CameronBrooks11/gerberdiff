# CLI reference

## `parse` -- inspect a single file

```sh
gerberdiff parse board.gbr
gerberdiff parse board.gbr --dump-ir    # JSON summary to stdout
gerberdiff parse board.gbr --verbose    # include info-level diagnostics
```

## `render` -- rasterise a single file to PNG

```sh
gerberdiff render board.gbr --out-png board.png
gerberdiff render board.gbr --out-png board.png --width 4096 --height 4096
gerberdiff render board.gbr --out-png board.png --overwrite
```

## `diff` -- compare two layer directories

```sh
gerberdiff diff before/ after/
gerberdiff diff before/ after/ --fail-on-diff          # exit 1 if changes found
gerberdiff diff before/ after/ --out-json report.json
gerberdiff diff before/ after/ --out-png diff_pngs/
gerberdiff diff before/ after/ --layer F.Cu --verbose
gerberdiff diff before/ after/ --align-offset 0.5,0    # shift board B by 0.5 in
```

### Options

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

### Overlay PNG colour scheme

| Colour | Meaning                                            |
| ------ | -------------------------------------------------- |
| Red    | Geometry present in **before** only (removed)      |
| Green  | Geometry present in **after** only (added)         |
| Grey   | Unchanged geometry (only with `--png-show-common`) |

## `geomdiff` -- geometry-aware diff of two layer directories

Resolution-independent, attributed changes computed on the parsed vector
geometry (Cairo-free). Classifies each change as `added`, `removed`,
`moved`, or `resized` -- including sub-pixel displacements invisible to
the raster diff. See [geometry-diff.md](geometry-diff.md).

```sh
gerberdiff geomdiff before/ after/
gerberdiff geomdiff before/ after/ --fail-on-diff       # exit 1 if changes found
gerberdiff geomdiff before/ after/ --out-json report.json
gerberdiff geomdiff before/ after/ --out-svg overlays/
gerberdiff geomdiff before/ after/ --layer F.Cu --verbose
gerberdiff geomdiff before/ after/ --move-tol 0.01      # 10 um move threshold
```

### Options

| Option                  | Default | Description                                       |
| ----------------------- | ------- | -------------------------------------------------- |
| `--move-tol MM`         | 0.005   | Min displacement (mm) to report `moved`            |
| `--gate-radius MM`      | 0.2     | Max distance (mm) to pair two objects as the same  |
| `--area-tol FRAC`       | 0.01    | Relative area delta still counted as same dims     |
| `--dust-area MM2`       | 1e-6    | Drop boolean-diff components smaller than this     |
| `--layer NAME`          | (all)   | Restrict to named layer (repeatable)               |
| `--out-json PATH`       | (none)  | Write geometry JSON report (schema v2)             |
| `--out-svg DIR`         | (none)  | Write per-layer SVG overlays                       |
| `--overwrite`           | false   | Allow overwriting existing output files            |
| `--fail-on-diff`        | false   | Exit 1 if any changes detected                     |
| `--quiet` / `--verbose` | (none)  | Suppress or expand terminal output                 |

### SVG overlay colour scheme

| Colour | Meaning                                                  |
| ------ | --------------------------------------------------------- |
| Red    | Removed object                                            |
| Green  | Added object                                              |
| Blue   | Moved object (after position, with a displacement line)  |
| Orange | Resized object (after fill, before outline)              |
