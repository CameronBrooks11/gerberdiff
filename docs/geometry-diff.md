# Geometry-Aware Diff

**Status: implemented** (`gerberdiff geomdiff`, `compute_geometry_diff`).

This document describes the geometry diff engine: why it exists, how it
works, and where it intentionally diverges from the raster engine.

---

## Why

The raster diff renders both revisions to pixel buffers and XORs them. That
answers "*where* did pixels change?" but is structurally unable to answer
"*what* changed?":

- It is **resolution-limited**: a $0.05\,\text{mm}$ pad shift is invisible
  below the pixel pitch and a smear of XOR crescents above it.
- It **cannot attribute** a change to an aperture, object, or net.
- It cannot distinguish a **moved** footprint from a **removed + added**
  one -- both render as red/green blobs.

On a real board pair (the A64-OlinuXino fixtures), a front-side component
relocation of $\approx 0.14\,\text{mm}$ rendered as an unreadable field of
red/green crescents. The geometry engine reports it as: 46 objects moved by
$(-0.139, -0.054)\,\text{mm}$, 81 removed, 160 added, 1211+ unchanged.

The two engines are complementary and both are kept (**hybrid
architecture**): raster for visual overlays, geometry for attributed,
machine-readable change analysis.

## Pipeline

```
ParsedImage (before)        ParsedImage (after)
       |                            |
  build_layer_geometry        build_layer_geometry      layer_geometry.py
       |  list[ExpandedOp]          |
       +------------+---------------+
                    |
          partition_unchanged                            attribute.py
          (exact signature cancellation)
                    |
       +------------+---------------+
       |                            |
  boolean_layer_diff          attribute_changes
  (added/removed areas)       (moved/resized/added/removed)
  geom_diff.py                attribute.py
       |                            |
       +------------+---------------+
                    |
            LayerGeometryDiff  ->  GeometryDiffResult    driver.py
                    |
        JSON schema v2 / SVG overlay                     export/
```

### Stage 1 -- Expansion (`expand.py`, `macro_geom.py`, `layer_geometry.py`)

Every draw operation becomes an `ExpandedOp` with **lazy** world-space
shapely geometry:

| Source                            | Shape                                                                |
| --------------------------------- | -------------------------------------------------------------------- |
| Circle/rect/obround/polygon flash | exact primitive (adaptive tessellation, $\leq 1\,\mu\text{m}$ chord) |
| Aperture hole                     | subtracted from the flash shape only (spec semantics)                |
| Macro flash                       | all 7 primitive types; exposure-0 subtracts within the macro         |
| Round-aperture stroke             | exact capsule (`LineString.buffer`)                                  |
| Non-round linear stroke           | **exact Minkowski sum** = convex hull of aperture at both endpoints  |
| Arc stroke (round)                | sampled polyline buffer at chord tolerance                           |
| Arc stroke (non-round)            | round-brush approximation + Info diagnostic                          |
| Region fill (G36/G37)             | polygon contours, even-odd combination                               |
| Block aperture flash              | flattened into the replay sequence (see polarity below)              |

Layer transforms (`%LM% %LR% %LS%`) and step-and-repeat compose into a
single affine per op, matching the renderer's CTM order
(SR-translate -> scale -> rotation -> mirror).

**Polarity** is an ordered replay: dark ops union into the accumulated
image, clear ops subtract (`resolve_geometry`). A clear layer inside a
block aperture erases previously drawn content globally -- matching
verified renderer behaviour -- so effective polarity is Clear when any
enclosing context is Clear.

### Stage 2 -- Exact cancellation (`attribute.partition_unchanged`)

Each op carries a **content signature** computed from its source (kind,
polarity, aperture *content* -- not D-code -- coordinates, affine, SR
tile). Identical source text parses to identical floats, so unchanged ops
produce bit-identical signatures across revisions and cancel without any
geometry construction. This is both a correctness device (exact, not
tolerance-based) and the engine's core performance property: on typical
revisions the vast majority of ops never expand.

### Stage 3 -- Boolean diff (`geom_diff.py`)

For all-dark layers (the common case):

```
added_raw   = union(B_only) - union(A_only)
removed_raw = union(A_only) - union(B_only)
added       = added_raw   - union(unchanged ops intersecting it)
removed     = removed_raw - union(unchanged ops intersecting it)
```

The reduction step is exact: unchanged material that does not intersect a
raw difference cannot affect it. Interaction is tested against analytic
bounding boxes (STRtree), so non-interacting unchanged ops are never
expanded. Differences are snap-rounded (GEOS `grid_size`) and components
below `--dust-area` are dropped as numeric noise.

Layers containing clear polarity fall back to differencing the full
ordered-replay geometry of both sides (correct, slower).

### Stage 4 -- Attribution (`attribute.py`)

Remaining (changed) ops are pooled by (kind, polarity) and matched A->B by
centroid proximity: KD-tree candidates within `--gate-radius`, accepted
greedily by ascending distance (deterministic). Each matched pair
classifies as:

| Condition                         | Kind                |
| --------------------------------- | ------------------- |
| same dims, offset > `--move-tol`  | `moved`             |
| same dims, offset <= `--move-tol` | (unchanged)         |
| different dims                    | `resized`           |
| unmatched in before / after       | `removed` / `added` |

"Same dims" compares an **orientation-normalised** aperture signature (a
$90^\circ$-rotated rect/obround footprint counts as the same pad) plus a
relative area check (`--area-tol`) that distinguishes a stretched stroke
from a translated one. Net names from `%TO.N%` attributes propagate onto
changes.

## Tolerances (CLI flags, mm)

| Flag            | Default | Meaning                                            |
| --------------- | ------- | --------------------------------------------------- |
| `--move-tol`    | 0.005   | Min displacement to report `moved` (5 um)           |
| `--gate-radius` | 0.2     | Max distance for two ops to pair as the same object |
| `--area-tol`    | 0.01    | Relative area delta still counted as same dims      |
| `--dust-area`   | 1e-6    | Min boolean-diff component area (mm^2) to keep      |

## Intentional divergences from the raster engine

The geometry engine follows the Gerber specification where the raster
engine takes compositing shortcuts. These are correctness *improvements*,
documented so the two engines' outputs are interpreted correctly:

1. **Aperture holes** are transparent (subtracted from the flash only);
   the raster engine's `DEST_OUT` punch erases underlying image content.
2. **Macro exposure-0** erases within the macro flash only; the raster
   engine erases the canvas globally.
3. **Macro primitive rotation** rotates the whole primitive around the
   macro origin (spec); the raster engine rotates primitives 21/5/6/7
   around their own centres. Identical when rotation is 0 or the centre
   is at the origin (the overwhelmingly common cases).
4. **Non-round linear strokes** are exact Minkowski sums; the raster
   engine strokes with width `max(w, h)`.

## Known limitations

- Strokes drawn with macro or block apertures are skipped (the raster
  engine draws them as hairlines; neither engine models them properly).
- `rerouted` classification is deferred: a redrawn trace reports as
  removed + added segments (or `resized` when endpoints stay close).
- Geometry changes are op-granular: a moved multi-op footprint reports
  one change per pad, not one change per component.

## Performance

Measured on the 15-layer A64-OlinuXino fixture pair: full diff
$\approx 20\,\text{s}$, identical-revision diff $\approx 8\,\text{s}$
(parse-dominated), single layer $\approx 0.3\,\text{s}$ -- versus
$16\,\text{s}$ for the raster engine at $2048^2$. Cost scales with the
amount of *changed* material, not board size.

## History

This engine was originally deferred (this document previously recorded the
deferral rationale and a design sketch). The investigation that triggered
the implementation -- including the determinism experiment that ruled out
anti-aliasing noise and the flash-matching oracle used as ground truth for
the integration tests -- is summarised in `tests/test_geometry_oracle.py`.
