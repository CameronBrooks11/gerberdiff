# JSON report schema (version 1)

All coordinate values are in **inches**.

## Top-level object

| Field | Type | Description |
|-------|------|-------------|
| `version` | `integer` | Schema version. Currently always `1`. |
| `generator` | `string` | Always `"gerberdelta"`. |
| `summary` | `object` | Aggregate counts across all layers (see below). |
| `layers` | `array[LayerResult]` | One entry per matched, added, or removed layer pair (see below). |

### `summary` object

| Field | Type | Description |
|-------|------|-------------|
| `changed_layers` | `integer` | Number of layers with `changed_pixel_count > 0` or status `"added"` / `"removed"`. |
| `total_regions` | `integer` | Total number of changed regions across all layers. |
| `has_changes` | `boolean` | `true` when any layer was added, removed, or has changed pixels. |

## `LayerResult` object

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Layer display name derived from the common file stem (e.g. `"A64-OlinuXino-F.Cu"`). |
| `status` | `"matched"` \| `"added"` \| `"removed"` | Whether the layer exists in both revisions, only the after revision, or only the before revision. |
| `layer_type` | `string` | Detected layer type.  One of: `"FCu"`, `"BCu"`, `"InCu"`, `"FMask"`, `"BMask"`, `"FPaste"`, `"BPaste"`, `"FSilk"`, `"BSilk"`, `"EdgeCuts"`, `"NPTH"`, `"PTH"`, `"Drill"`, `"Unknown"`. |
| `changed_pixel_count` | `integer` | Number of pixels that differ between the before and after renders of this layer. `0` for added/removed layers (use `status` to distinguish). |
| `total_pixel_count` | `integer` | Total pixels in the render canvas (width × height). |
| `changed_fraction` | `number` | `changed_pixel_count / total_pixel_count`, rounded to 8 decimal places. |
| `regions` | `array[Region]` | Changed regions detected by connected-component labelling (see below). Empty for unchanged layers. |

## `Region` object

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | 1-based region index within this layer. |
| `centroid_x` | `number` | X coordinate of the region centroid in inches. |
| `centroid_y` | `number` | Y coordinate of the region centroid in inches. |
| `bbox` | `object` | Axis-aligned bounding box of the region (see below). |
| `pixel_count` | `integer` | Number of changed pixels in this region (always >= `--min-pixels`, default 4). |

### `bbox` object

| Field | Type | Description |
|-------|------|-------------|
| `min_x` | `number` | Left edge of the bounding box in inches. |
| `min_y` | `number` | Bottom edge of the bounding box in inches (Gerber +Y-up convention). |
| `max_x` | `number` | Right edge of the bounding box in inches. |
| `max_y` | `number` | Top edge of the bounding box in inches. |

## Example

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
