# Geometry-Aware Diff -- Why It Was Not Implemented

**Status:** Intentionally deferred. This note explains the decision and records enough
design detail that the work can be picked up cleanly by a future contributor.

---

## What We Have (Raster Diff)

The current diff engine renders both Gerber files to pixel buffers via Cairo and XORs
them. The result is a visual overlay and a list of changed screen-space regions. This
is resolution-limited (changes smaller than one pixel are invisible) and cannot
attribute a change to a specific aperture, net, or DrawOp.

## What Geometry-Aware Diff Would Add

A geometry diff operates on the parsed coordinate IR and is resolution-independent. It
can detect:

- A pad that moved 0.05 mm (subpixel at default resolution)
- A via diameter that changed from 0.3 mm to 0.25 mm
- A trace re-routed between the same endpoints
- A net attribute change (`%TO.N,...%`) with no geometric change

These are the change classes that matter most in a manufacturing context.

## Why It Was Not Implemented

The raster diff was sufficient for the stated use case (human review of board revisions)
and the three-stage geometry pipeline below carries significant implementation risk
concentrated in aperture expansion and change attribution. Deferring it avoided
blocking the v1.0 release gate while preserving a clean foundation to build on.

The parsed IR (`ParsedImage`, `DrawOp`, `ArcSegment`) is already structured to support
the geometry layer without modification.

---

## How It Would Be Done

### Stage A -- Aperture Expansion

Every `DrawOp` represents an intent; the geometry diff needs the actual shape -- a
polygon. Required expansions:

| DrawOp                    | Expansion                                              |
| ------------------------- | ------------------------------------------------------ |
| Circle flash              | Circle -> regular polygon approximation                 |
| Rectangle flash           | Axis-aligned rectangle                                 |
| Obround flash             | Rectangle + two semicircles                            |
| Polygon flash             | Regular N-gon                                          |
| Macro flash               | Evaluated primitive set -> union of polygons            |
| Block flash               | Recursive expansion of contained ops                   |
| D01 stroke (any aperture) | Minkowski sum of aperture shape with path              |
| Arc stroke                | Swept shape along arc; use `ArcSegment` geometry       |
| Region fill (G36/G37)     | Already a polygon; direct use (prerequisite: item 5.6) |

**Recommended library:** `shapely` (LGPL-2.1, compatible with Apache-2.0). It provides
polygon construction, `buffer()` for Minkowski approximation, boolean operations, and
area/centroid queries.

Arc stroke expansion is the hardest case. Suggested tolerance: chord error <= 1 um
(~ 64 segments per full circle at 0.5 mm diameter). Complex macros may need a
bounding-box fallback to avoid performance problems on dense boards.

### Stage B -- Per-Layer Boolean Difference

```python
added_area   = unary_union(polygons_b).difference(unary_union(polygons_a))
removed_area = unary_union(polygons_a).difference(unary_union(polygons_b))
```

Operate once per matched layer pair from `match_layers()`.

### Stage C -- Change Attribution

Match each changed polygon back to its source `DrawOp` objects by spatial intersection.
Classify:

- Shape in A only -> **removed**
- Shape in B only -> **added**
- Same location, same aperture type, different dimensions -> **resized**
- Same bounding-box centroid, different path -> **rerouted**

Matching is heuristic. Suggested: centroid within `0.5 x min(aperture_diameter)` of the
smaller shape. This needs user-tunable tolerance.

### Recommended Architecture

**Hybrid** -- keep the raster engine for visual output; add the geometry engine as a
parallel pipeline producing a `GeometryDiffResult` alongside the existing
`SingleLayerDiff`. The two outputs serve different audiences (human review vs.
automated inspection).

Do not remove the raster overlay. Do not derive the raster from the geometry polygons
(Option C in the original roadmap) -- it adds complexity for no user-visible benefit in
the common case.

### Sketch of New Types

```python
@dataclass
class GeometryChange:
    kind: Literal["added", "removed", "resized", "rerouted"]
    layer_name: str
    layer_type: LayerType
    centroid_x: float          # inches
    centroid_y: float          # inches
    area_mm2: float
    before_op: DrawOp | None
    after_op: DrawOp | None
    net_name: str | None       # from DrawOp.attributes["N"] if present

@dataclass
class LayerGeometryDiff:
    name: str
    layer_type: LayerType
    changes: list[GeometryChange]
    added_area_mm2: float
    removed_area_mm2: float

@dataclass
class GeometryDiffResult:
    layers: list[LayerGeometryDiff]
    has_changes: bool
```

The JSON report schema would need a version bump to include this structure.

---

## Prerequisites Before Starting

1. **Item 5.6 complete** -- `RegionFill` must be its own IR type (not sentinel `DrawOp`
   values) so Stage A can handle region fills without special-casing.
2. **Prototype against real boards** -- run aperture expansion and boolean diff on at
   least two of the fixture boards before committing the full pipeline.
3. **`shapely` dependency decision** -- confirm LGPL-2.1 is acceptable; add to
   `[project.dependencies]` in `pyproject.toml`.
