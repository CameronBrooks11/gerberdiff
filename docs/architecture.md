# Architecture

## Overview

gerberdiff is a diff tool for Gerber and Excellon PCB design files. It turns
the question "what changed between two board revisions?" into visual overlays
and machine-readable reports via two complementary engines that share the
same parse layer:

- the **raster engine** (`render/` + `diff/`) -- Cairo rasterisation + pixel
  XOR; produces visual overlay PNGs and screen-space changed regions;
- the **geometry engine** (`geometry/`) -- shapely vector geometry; produces
  resolution-independent, attributed changes (`moved`/`resized`/`added`/
  `removed`) and is Cairo-free. See [geometry-diff.md](geometry-diff.md).

```
                Gerber/Excellon files
                         |
                         v
                  +-------------+
                  |    parse/   |  tokenise -> state machine -> ParsedImage IR
                  +------+------+
                         |  ParsedImage
            +------------+--------------+
            |                           |
            v                           v
  +-------------+              +---------------+
  |   render/   |              |   geometry/   |  expand ops -> shapely,
  |  viewport ->|              |  signatures ->|  exact cancellation,
  |  Cairo ->   |              |  boolean diff |  KD-tree attribution
  |  numpy      |              +-------+-------+
  +------+------+                      |
         |  numpy BGRA                 |  GeometryDiffResult
         v                             |
  +-------------+                      |
  |    diff/    |  XOR -> scipy CCL    |
  +------+------+                      |
         |  DiffResult                 |
         +------------+----------------+
                      v
               +-------------+
               |   export/   |  JSON v1/v2, overlay PNG, SVG
               +-------------+
```

---

## Module map

### `gerberdiff/parse/`

| File                 | Purpose                                                                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `tokenizer.py`       | Splits a Gerber file into a flat stream of `Token` objects (param blocks, data blocks, D/G/M codes)                                         |
| `gerber_parser.py`   | Utility functions: `parse_format_statement`, `convert_coordinate`, `parse_aperture_definition` -- called directly by `gerber_state.py`      |
| `gerber_state.py`    | Full RS-274X state machine; consumes the token stream from `tokenize_gerber` and emits `DrawOp` / `RegionFill` objects into a `ParsedImage` |
| `macro_parser.py`    | Parses and evaluates aperture macro expressions; produces `MacroDef` objects used by the renderer                                           |
| `arc_math.py`        | Converts Gerber centre-offset arc representation to `ArcSegment` (centre + radius + start/end angles)                                       |
| `excellon_parser.py` | Parses Excellon drill files (header + body) into a `ParsedImage` using the same IR                                                          |

### `gerberdiff/render/`

| File                 | Purpose                                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------------------- |
| `viewport.py`        | Fits a `BoundingBox` into pixel canvas dimensions -> `Viewport` (pan/zoom + Y-flip)                         |
| `compiled_render.py` | Translates a `ParsedImage` IR into a flat list of `DrawOp` objects                                          |
| `draw_ops.py`        | Low-level cairocffi primitives for each draw operation (stroke, fill, flash, arc)                           |
| `macro_renderer.py`  | Evaluates `MacroDef` primitives (circle, line, outline, polygon, thermal, moire, custom) to cairocffi paths |
| `renderer.py`        | Orchestrates: creates `cairo.ImageSurface`, calls compiled render + draw-ops, returns numpy BGRA array      |

### `gerberdiff/diff/`

| File               | Purpose                                                                                                    |
| ------------------ | ---------------------------------------------------------------------------------------------------------- |
| `diff_engine.py`   | Renders both images to a shared viewport, XORs RGB channels, runs scipy CCL, returns `SingleLayerDiff`     |
| `layer_matcher.py` | Pairs files from two directories by stem; classifies each by `LayerType`; returns sorted `list[LayerPair]` |

### `gerberdiff/geometry/`

| File                | Purpose                                                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `primitives.py`     | Adaptive-tessellation shapely shape builders (circle, rect, obround, n-gon, arc sampling)                      |
| `macro_geom.py`     | Macro primitives -> shapely with spec-compliant exposure scoping and rotation                                  |
| `expand.py`         | Flash/stroke/region expansion: exact Minkowski strokes, even-odd regions                                       |
| `layer_geometry.py` | Lazy `ExpandedOp` assembly: source-based signatures, polarity replay, transforms, S&R, block flattening        |
| `geom_diff.py`      | Boolean added/removed material with exact-cancellation fast path                                               |
| `attribute.py`      | Exact + KD-tree matching; classifies `moved` / `resized` / `added` / `removed`                                 |
| `driver.py`         | `compute_geometry_diff`: directory pairing (reuses `layer_matcher`), per-layer orchestration                   |
| `types.py`          | Public result types: `GeometryChange`, `LayerGeometryDiff`, `GeometryDiffResult`                               |

### `gerberdiff/export/`

| File             | Purpose                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| `json_report.py` | Builds versioned JSON diff reports: v1 from a `DiffResult`, v2 from a `GeometryDiffResult`       |
| `png_export.py`  | Builds a colour-coded overlay PNG: red = removed, green = added, yellow = changed, grey = common |
| `svg_export.py`  | Cairo-free SVG overlay for geometry diffs (red/green/blue/orange change kinds)                   |

### `gerberdiff/`

| File       | Purpose                                                                      |
| ---------- | ----------------------------------------------------------------------------- |
| `types.py` | All shared IR dataclasses and enums (see below)                              |
| `cli.py`   | Click entry point; subcommands: `parse`, `render`, `diff`, `geomdiff`        |

---

## Internal representation (IR)

All coordinate values are in **inches** throughout the IR. The parse layer
converts from whatever unit the file uses (inches or mm) before emitting nets.

### Key types (`gerberdiff/types.py`)

```
ParsedImage
+-- draw_ops: list[DrawOp | RegionFill]  <- one entry per drawing operation
+-- apertures: dict[int, Aperture]       <- keyed by D-code number
+-- layers: list[LayerState]             <- polarity, rotation, mirror, scale, S&R
+-- coord_states: list[CoordState]       <- coordinate format, unit, offsets
+-- bounding_box: BoundingBox            <- axis-aligned hull in inches
+-- diagnostics: list[Diagnostic]
```

```
DrawOp
+-- start_x / start_y / stop_x / stop_y  (inches)
+-- aperture_index, aperture_state        (Off / On / Flash)
+-- interpolation                         (Linear / CW / CCW)
+-- layer_index, coord_state_index
+-- arc_segment: ArcSegment | None        (fully resolved, angles in degrees)
```

Aperture union type:
`CircleAperture | RectangleAperture | ObroundAperture | PolygonAperture | MacroAperture | BlockAperture`

---

## Coordinate system and viewport

Gerber uses a right-handed coordinate system (+Y up). Cairo uses +Y down.
The viewport transform applies a Y-flip:

$$s_x = p_x + w_x \cdot z$$

$$s_y = p_y - w_y \cdot z$$

where $(s_x, s_y)$ are screen (pixel) coordinates, $(w_x, w_y)$ are world
(inch) coordinates, $(p_x, p_y)$ is the pan offset, and $z$ is the zoom
factor (pixels per inch).

The zoom is computed to fit the bounding box into the canvas with a 10% margin:

$$z = 0.9 \cdot \min\!\left(\frac{W}{b_w},\, \frac{H}{b_h}\right)$$

where $W, H$ are the canvas dimensions in pixels and $b_w, b_h$ are the
bounding box width and height in inches. The pan is then set so the board
centre maps to the canvas centre:

$$p_x = \frac{W}{2} - c_x \cdot z \qquad p_y = \frac{H}{2} + c_y \cdot z$$

The inverse transform (`screen_to_world`) recovers world coordinates from
pixel coordinates:

$$w_x = \frac{s_x - p_x}{z} \qquad w_y = -\frac{s_y - p_y}{z}$$

`compute_viewport` fits the board's bounding box into the canvas with a 10%
margin. `merge_bounding_boxes` is used by the diff engine to derive a single
shared viewport so both images are aligned before pixel comparison.

---

## Raster diff algorithm

The geometry engine's algorithm is documented separately in
[geometry-diff.md](geometry-diff.md); it shares step 1 (layer matching).

1. **Layer matching** (`layer_matcher.py`) -- pairs files from two directories by file stem.
   Files present only in one directory are recorded as `status="added"` or `"removed"`.
   Results are sorted by a canonical layer order (F.Cu -> B.Cu -> inner Cu -> masks ->
   paste -> silk -> edge cuts -> drill -> unknown).

2. **Shared viewport** (`diff_engine.py`) -- merges the bounding boxes of both images
   so that both are rasterised at the same scale and position.

3. **XOR** -- RGB channels of the two BGRA numpy arrays are XORed.
   A pixel is "changed" when any RGB channel differs (alpha is ignored).

4. **Connected-component labelling (CCL)** -- `scipy.ndimage.label` with 4-connectivity
   identifies contiguous regions of changed pixels.

5. **Region extraction** -- `find_objects` + `center_of_mass` produce pixel-space
   bounding boxes and centroids, which are converted to inch coordinates via
   `screen_to_world`.

6. **Merge** -- `merge_overlapping_regions` iteratively merges regions whose bounding
   boxes overlap within a configurable tolerance (default 0.05 in).

---

## Extension points

**New aperture type** -- add an `@dataclass` to `types.py`, add a `Literal` arm to
the `Aperture` type alias, handle the new type in `gerber_state.py` (parsing) and
`compiled_render.py` / `draw_ops.py` (rendering).

**New exporter** -- add a module under `gerberdiff/export/`, accept a `DiffResult`
and write output; wire it into the `diff` subcommand in `cli.py`.

**New file format** -- add a parser module under `gerberdiff/parse/` that produces
a `ParsedImage`; the entire render/diff pipeline works unchanged downstream.
