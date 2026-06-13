# JSON report schemas

Two report formats exist:

- **Version 1** -- raster pixel diff (`gerberdiff diff --out-json`).
- **Version 2** -- geometry diff (`gerberdiff geomdiff --out-json`),
  distinguished by `"mode": "geometry"`.

## Schema version 1 (raster diff)

All coordinate values are in **inches**.

## Top-level object

| Field       | Type                 | Description                                                      |
| ----------- | -------------------- | ---------------------------------------------------------------- |
| `version`   | `integer`            | Schema version. Currently always `1`.                            |
| `generator` | `string`             | Always `"gerberdiff"`.                                          |
| `summary`   | `object`             | Aggregate counts across all layers (see below).                  |
| `layers`    | `array[LayerResult]` | One entry per matched, added, or removed layer pair (see below). |

### `summary` object

| Field            | Type      | Description                                                                        |
| ---------------- | --------- | ---------------------------------------------------------------------------------- |
| `changed_layers` | `integer` | Number of layers with `changed_pixel_count > 0` or status `"added"` / `"removed"`. |
| `total_regions`  | `integer` | Total number of changed regions across all layers.                                 |
| `has_changes`    | `boolean` | `true` when any layer was added, removed, or has changed pixels.                   |

## `LayerResult` object

| Field                 | Type                                    | Description                                                                                                                                                                           |
| --------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                | `string`                                | Layer display name derived from the common file stem (e.g. `"A64-OlinuXino-F.Cu"`).                                                                                                   |
| `status`              | `"matched"` \| `"added"` \| `"removed"` | Whether the layer exists in both revisions, only the after revision, or only the before revision.                                                                                     |
| `layer_type`          | `string`                                | Detected layer type. One of: `"FCu"`, `"BCu"`, `"InCu"`, `"FMask"`, `"BMask"`, `"FPaste"`, `"BPaste"`, `"FSilk"`, `"BSilk"`, `"EdgeCuts"`, `"NPTH"`, `"PTH"`, `"Drill"`, `"Unknown"`. |
| `changed_pixel_count` | `integer`                               | Number of pixels that differ between the before and after renders of this layer. `0` for added/removed layers (use `status` to distinguish).                                          |
| `total_pixel_count`   | `integer`                               | Total pixels in the render canvas ($\text{width} \times \text{height}$).                                                                                                            |
| `changed_fraction`    | `number`                                | $\texttt{changed\_pixel\_count} / \texttt{total\_pixel\_count}$, rounded to 8 decimal places.                                                                                        |
| `regions`             | `array[Region]`                         | Changed regions detected by connected-component labelling (see below). Empty for unchanged layers.                                                                                    |

## `Region` object

| Field         | Type      | Description                                                                    |
| ------------- | --------- | ------------------------------------------------------------------------------ |
| `id`          | `integer` | 1-based region index within this layer.                                        |
| `centroid_x`  | `number`  | X coordinate of the region centroid in inches.                                 |
| `centroid_y`  | `number`  | Y coordinate of the region centroid in inches.                                 |
| `bbox`        | `object`  | Axis-aligned bounding box of the region (see below).                           |
| `pixel_count` | `integer` | Number of changed pixels in this region (always >= `--min-pixels`, default 4). |

### `bbox` object

| Field   | Type     | Description                                                          |
| ------- | -------- | -------------------------------------------------------------------- |
| `min_x` | `number` | Left edge of the bounding box in inches.                             |
| `min_y` | `number` | Bottom edge of the bounding box in inches (Gerber +Y-up convention). |
| `max_x` | `number` | Right edge of the bounding box in inches.                            |
| `max_y` | `number` | Top edge of the bounding box in inches.                              |

## Example

```json
{
  "version": 1,
  "generator": "gerberdiff",
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
      "changed_fraction": 0.00033426,
      "regions": [
        {
          "id": 1,
          "centroid_x": 1.234,
          "centroid_y": 0.987,
          "bbox": {
            "min_x": 1.21,
            "min_y": 0.97,
            "max_x": 1.26,
            "max_y": 1.0
          },
          "pixel_count": 84
        }
      ]
    }
  ]
}
```

---

## Schema version 2 (geometry diff)

Coordinates (`centroid_x`, `centroid_y`) are in **inches** (matching v1);
areas are in **mm^2** and displacements in **mm**.

### Top-level object

| Field        | Type                         | Description                                        |
| ------------ | ---------------------------- | -------------------------------------------------- |
| `version`    | `integer`                    | Always `2`.                                        |
| `generator`  | `string`                     | Always `"gerberdiff"`.                             |
| `mode`       | `string`                     | Always `"geometry"`.                               |
| `summary`    | `object`                     | Aggregate counts (see below).                      |
| `tolerances` | `object` (optional)          | Classification thresholds used (reproducibility).  |
| `layers`     | `array[GeometryLayerResult]` | One entry per matched/added/removed layer pair.    |

### `summary` object

| Field            | Type      | Description                                          |
| ---------------- | --------- | ----------------------------------------------------- |
| `changed_layers` | `integer` | Layers with any change, non-matched status, or area.  |
| `total_changes`  | `integer` | Total attributed change records across all layers.    |
| `has_changes`    | `boolean` | `true` when anything differs.                          |

### `tolerances` object

| Field           | Type     | Description                                       |
| --------------- | -------- | -------------------------------------------------- |
| `move_tol_mm`   | `number` | Min displacement (mm) reported as `moved`.         |
| `gate_radius_mm`| `number` | Max pairing distance (mm).                          |
| `area_tol`      | `number` | Relative area delta counted as same dimensions.    |
| `dust_area_mm2` | `number` | Min boolean-diff component area kept (mm^2).       |

### `GeometryLayerResult` object

| Field              | Type                                    | Description                                                  |
| ------------------ | --------------------------------------- | ------------------------------------------------------------- |
| `name`             | `string`                                | Layer display name (common file stem).                       |
| `status`           | `"matched"` \| `"added"` \| `"removed"` | Presence across the two revisions.                           |
| `layer_type`       | `string`                                | Same vocabulary as schema v1.                                |
| `unchanged_count`  | `integer`                               | Ops identical between revisions (exact + sub-tolerance).     |
| `added_area_mm2`   | `number`                                | Material present only in the after revision.                 |
| `removed_area_mm2` | `number`                                | Material present only in the before revision.                |
| `counts`           | `object`                                | `{added, removed, moved, resized}` change-kind counts.       |
| `changes`          | `array[GeometryChange]`                 | Attributed changes, sorted top-of-board first.               |

### `GeometryChange` object

| Field        | Type                                                  | Description                                                       |
| ------------ | ----------------------------------------------------- | ------------------------------------------------------------------ |
| `kind`       | `"added"` \| `"removed"` \| `"moved"` \| `"resized"`  | Change classification.                                            |
| `op_kind`    | `"flash"` \| `"stroke"` \| `"region"`                 | Kind of drawing operation.                                        |
| `centroid_x` | `number`                                              | X centroid (inches) of the after-state object (before for `removed`). |
| `centroid_y` | `number`                                              | Y centroid (inches), Gerber +Y-up convention.                     |
| `area_mm2`   | `number`                                              | Area of the affected object.                                      |
| `dx_mm`      | `number` \| `null`                                    | X displacement (after - before); `null` for added/removed.       |
| `dy_mm`      | `number` \| `null`                                    | Y displacement; `null` for added/removed.                         |
| `net`        | `string` \| `null`                                    | Net name from `%TO.N%` attributes, when present.                  |

### Example

```json
{
  "version": 2,
  "generator": "gerberdiff",
  "mode": "geometry",
  "summary": { "changed_layers": 1, "total_changes": 2, "has_changes": true },
  "tolerances": {
    "move_tol_mm": 0.005,
    "gate_radius_mm": 0.2,
    "area_tol": 0.01,
    "dust_area_mm2": 1e-6
  },
  "layers": [
    {
      "name": "A64-OlinuXino-F.Paste",
      "status": "matched",
      "layer_type": "FPaste",
      "unchanged_count": 1215,
      "added_area_mm2": 17.741,
      "removed_area_mm2": 24.429,
      "counts": { "added": 0, "removed": 1, "moved": 1, "resized": 0 },
      "changes": [
        {
          "kind": "moved",
          "op_kind": "flash",
          "centroid_x": 5.1234,
          "centroid_y": -2.4567,
          "area_mm2": 0.2745,
          "dx_mm": -0.139,
          "dy_mm": -0.054,
          "net": "VCC"
        },
        {
          "kind": "removed",
          "op_kind": "flash",
          "centroid_x": 5.4321,
          "centroid_y": -2.5678,
          "area_mm2": 0.1963,
          "dx_mm": null,
          "dy_mm": null,
          "net": null
        }
      ]
    }
  ]
}
```
