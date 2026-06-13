# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Degenerate region contours no longer leak line geometry** -- a G36/G37
  contour whose points are collinear produced a zero-area `MultiLineString`
  from `make_valid` that flowed into the geometry engine; region expansion
  now keeps only polygonal parts.

### Changed

- Local coverage floor aligned with the CI gate (`fail_under` 85 -> 90;
  actual coverage is ~94%).
- Stale documentation corrected: the overlay-PNG colour table no longer
  lists the removed "yellow" class; `SECURITY.md` supported versions
  updated from 0.14.x to 0.29.x; `CONTRIBUTING.md` blesses
  conventional-commit prefixes (matching recent history).
- Package `__init__` modules for `parse`, `render`, `diff`, and `export`
  gained one-line docstrings.

### Added

- Edge-case test suite for the geometry engine's guard paths: block
  nesting depth limit, invalid layer indices, zero-dimension apertures,
  degenerate regions and strokes, macro flash dispatch, the
  equal-geometry attribution guard, and driver diagnostic forwarding.

## [0.29.1] - 2026-06-13

### Changed

- **Package metadata reflects both engines** -- the PyPI `description`
  and the CLI group help text described only the raster engine; both now
  cover the raster overlay and geometry diff pipelines. Added `geometry`
  and `shapely` to the package keywords. No behaviour changes.

## [0.29.0] - 2026-06-12

### Added

- **Geometry diff engine** (`gerberdiff/geometry/`) -- a second,
  Cairo-free diff pipeline operating on the parsed vector geometry via
  `shapely`. Resolution-independent and attributed: each change is
  classified as `added`, `removed`, `moved` (with dx/dy displacement,
  down to micrometres), or `resized`, with net names from `%TO.N%`
  attributes propagated onto changes. The raster engine is unchanged;
  the two are complementary (hybrid architecture). See
  `docs/geometry-diff.md`.

  - Aperture expansion: exact primitives with adaptive tessellation
    (<= 1 um chord tolerance); exact Minkowski sums for non-round
    linear strokes (convex hull of the aperture at both endpoints);
    all 7 macro primitive types with spec-compliant exposure scoping;
    region fills with even-odd contour semantics; aperture holes
    subtracted from the flash only (spec semantics).
  - Polarity as ordered boolean replay (dark unions, clear subtracts),
    including block apertures flattened into the outer replay with
    renderer-verified global-erase semantics for block-internal clears.
  - Exact-cancellation matching: ops carry source-based content
    signatures (aperture *content*, not D-code numbering), so unchanged
    ops cancel exactly and -- via lazy expansion -- never construct
    geometry at all.
  - Boolean added/removed material per layer with snap-rounded
    differences and a dust filter; full ordered-replay fallback when
    clear polarity is present.
  - Attribution: KD-tree gated matching with tunable tolerances
    (`move_tol`, `gate_radius`, `area_tol`); orientation-normalised
    dimension comparison so a 90-degree-rotated footprint classifies
    as `moved`, not `resized`.

- **`gerberdiff geomdiff` CLI subcommand** with `--move-tol`,
  `--gate-radius`, `--area-tol`, `--dust-area` (mm units), `--out-json`,
  `--out-svg`, `--layer`, `--fail-on-diff`, `-q`/`-v`.

- **JSON report schema version 2** (`"mode": "geometry"`): per-layer
  change counts, added/removed areas (mm^2), per-change records with
  centroid/area/displacement/net, and the tolerances used. Documented
  in `docs/schema.md`.

- **SVG overlay export** (`export/svg_export.py`, Cairo-free): removed
  red, added green, moved blue with displacement lines, resized orange;
  even-odd fill preserves aperture holes.

- **Public API**: `compute_geometry_diff`, `GeometryChange`,
  `LayerGeometryDiff`, `GeometryDiffResult` exported from the top-level
  package.

- **Dependency**: `shapely >= 2.0` (binary wheels with bundled GEOS; no
  system library required). Dev dependency `types-shapely` for mypy.

- 127 new tests, including a differential test pinning resolved
  geometry to the Cairo renderer's occupancy (>= 99% pixel agreement)
  and fixture-board integration tests against an independently computed
  flash-matching oracle.

### Changed

- **Cairo is now imported lazily.** `import gerberdiff` no longer
  requires the native cairo library; the parse and geometry pipelines
  (including `gerberdiff geomdiff` and `gerberdiff parse`) work on
  systems without it. Accessing the rasteriser (`render_to_numpy`,
  `render_to_surface`, `compute_diff`, or the `render`/`diff` CLI
  commands) raises the underlying `OSError` only when actually used.
  Raster-engine tests skip cleanly when cairo is unavailable, which
  fixes the previously failing Windows CI job.

- **Project renamed from `gerberdelta` to `gerberdiff`** (2026-04-25,
  unreleased at the time). 0.29.0 is the first published release under
  the new name; no release was ever made as `gerberdelta`. The rename
  window also included: docs reorganised to lowercase-kebab filenames
  with split CLI/API references, an ASCII-only character policy sweep,
  LaTeX math notation for equations in docs, and strict mypy
  annotations across the test suite.

## [0.28.0] - 2026-04-25

### Added

- **Render/diff regression coverage** -- 411 lines of new tests across
  the renderer, draw-ops, diff engine, and parser: incremental (G91)
  coordinates, step-and-repeat tiling, layer transforms (LM/LR/LS),
  clear-polarity compositing, region merge cascade, polygon aperture
  rotation, macro `unit_scale`, `alignment_offset`, and pixel-level
  render verification. No production code changes.

## [0.27.0] - 2026-04-25

### Changed

- **`CompiledRender` cached per `BlockAperture`** -- repeated flashes of
  the same block aperture no longer recompile its draw-op groups on
  every flash. The cache is keyed by `id(block_ap)` and evicted by a
  `weakref` finalizer when the aperture is garbage-collected, so stale
  ids cannot produce false hits.

## [0.26.0] - 2026-04-25

### Fixed

- **Rect/obround stroke width** -- D01 strokes with rectangle or obround
  apertures are drawn with line width `max(width, height)` instead of
  `min(width, height)`, so traces whose long axis aligns with the stroke
  direction (the common case) are no longer under-stroked; documented as
  an approximation pending geometry-aware rendering.
- **Macro evaluation failures no longer abort the render** -- a macro
  aperture whose primitive evaluation raises is skipped with a
  `UserWarning` instead of crashing the whole render pass.

## [0.25.0] - 2026-04-25

### Fixed

- **Parser correctness sweep** --
  - arc bounding boxes account for axis-extrema crossings (0/90/180/270
    degrees), not just the endpoints;
  - step-and-repeat tiles expand the image bounding box and respect
    layer polarity;
  - block aperture (`%AB%`) parsing isolates state correctly (nested
    apertures/layers no longer leak into the parent image);
  - `_apply_format` no longer truncates coordinates with more integer
    digits than the format statement declares;
  - referencing an unknown macro in an aperture definition is an
    `Error`-severity diagnostic (was silently tolerated).

## [0.24.0] - 2026-04-25

### Changed

- **`DiffResult.has_changes` is a computed property** -- derived from the
  layer results instead of stored at construction, so it cannot drift
  from the data.
- **Excellon parser refactored** -- the nonlocal-closure state pattern is
  replaced with explicit local parser state; behaviour unchanged.

## [0.23.0] - 2026-04-25

### Added

- **`compute_full_diff`** -- directory-vs-directory diff as a single
  public API call (parse, match, diff, assemble `DiffResult`), with
  `overlay_callback` and `on_diagnostic` hooks.
- **All IR and result types exported** from the top-level package with
  an `__all__` list; README gains API examples.

### Changed

- `diff_cmd` rewritten on top of `compute_full_diff` (the CLI no longer
  duplicates the orchestration logic).

## [0.22.0] - 2026-04-25

### Added

- **`docs/schema.md`** -- canonical JSON report schema documentation.
- **CI hardening** -- coverage gate (`--cov-fail-under=90`), a Windows
  test job in the matrix, and a non-ASCII character check.

### Changed

- **`EXCELLON_SUFFIXES` is public** -- renamed from `_EXCELLON_SUFFIXES`
  in `diff/layer_matcher.py`; it is part of the de-facto API used by the
  CLI and downstream callers.

## [0.21.0] - 2026-04-25

### Changed

- **`RegionFill` IR redesign** -- G36/G37 region fill boundaries are no
  longer stored as sentinel `DrawOp` objects with
  `InterpolationMode.RegionStart` / `RegionEnd`. A new `RegionFill`
  dataclass (`layer_index`, `net_state_index`, `segments: list[DrawOp]`)
  is emitted by the parser as a single item. `ParsedImage.draw_ops` and
  `BlockAperture.draw_ops` are now typed `list[DrawOp | RegionFill]`.
  `InterpolationMode.RegionStart` and `InterpolationMode.RegionEnd` are
  removed. `compiled_render.py` handles `RegionFill` directly without a
  state-machine sentinel scan. `RegionFill` is exported from the public
  API. Unclosed G36 at M02 now correctly emits a `Warning` diagnostic.

## [0.20.0] - 2026-04-25

### Changed

- **`_EXCELLON_SUFFIXES` consolidated** -- the duplicate definition in
  `cli.py` is removed; `cli.py` now imports `_EXCELLON_SUFFIXES` from
  `diff/layer_matcher.py`, which remains the single source of truth.

- **`_flush_macro` exception severity upgraded to `Error`** -- a failed
  `parse_macro_body` call (e.g. non-integer variable index `$notanint=...`)
  was silently recorded as a `Warning` with `# pragma: no cover`. It is now
  recorded as `DiagnosticSeverity.Error`, the `# pragma: no cover` tag is
  removed, and a test exercises this path.

- **Fixture paths in tests use `__file__`-relative construction** -- all
  ten `Path("tests/fixtures/...")` occurrences across seven test files are
  replaced with `Path(__file__).parent / "fixtures" / "..."`. Tests now pass
  regardless of the working directory from which pytest is invoked.

- **`--align-offset` Y direction corrected** -- positive `DY` now shifts
  image B downward (positive screen Y), consistent with `DX` shifting
  rightward. Previously positive `DY` moved the geometry upward, which was
  the inverse of the expected screen convention. Help text updated to
  document the convention explicitly.

- **`CoordState` deprecated fields removed** -- `mirror_state`, `axis_select`,
  `offset_a`, `offset_b`, `scale_a`, and `scale_b` were never populated by
  the parser (the corresponding `%MI%`, `%AS%`, `%OF%`, `%SF%` commands were
  handled with `pass`). `CoordState` now carries only `unit: UnitType`.

## [0.19.0] - 2026-04-25

### Added

- **Public Python API** (`gerberdiff/__init__.py`) -- `parse_gerber`,
  `parse_excellon`, `render_to_surface`, `render_to_numpy`, and `compute_diff`
  are now exported from the top-level package with an `__all__` list. Added a
  `## Python API` section to `README.md` with example usage.

### Changed

- **`SingleLayerDiff` no longer stores raw pixel arrays** -- `arr_a`, `arr_b`,
  and `xor` (three `~48 MB` numpy arrays at 2048^2) have been removed from the
  dataclass. Callers that need a PNG overlay pass an `overlay_callback:
Callable[[ndarray, ndarray, ndarray], None]` to `compute_diff()`; the callback
  is invoked before the arrays are released. The diff CLI uses this callback to
  write the overlay PNG without ever holding all three arrays simultaneously.

- **`_parse` closure in `diff_cmd` returns `ParsedImage`** -- the return type
  annotation was `object` with `# type: ignore[assignment]`; it is now correctly
  typed as `ParsedImage`, and the ignore comment is removed.

- **`_GerberParser._block_stack` uses `_BlockFrame` dataclass** -- replaces the
  unnamed 7-tuple `(d_code, block_ap, saved_nets, saved_layers, saved_apertures,
saved_bbox, saved_layer_idx)` with a named `_BlockFrame` dataclass so that
  field access is explicit and mypy-checked.

### Fixed

- **Dead `changed`/yellow pixel path removed from `png_export.py`** -- both
  images are rendered with the same colour scheme so the `changed` mask (pixels
  present in both A and B with different colour values) is structurally always
  empty. The unreachable `out[changed] = [0, 255, 255, 255]` line and the
  `changed` variable have been removed.

## [0.18.0] - 2026-04-25

### Changed

- **`LayerType` moved to `types.py`** -- `LayerType` was defined in
  `diff/layer_matcher.py` but is a domain type used across the IR, diff, export,
  and CLI layers. Moving it to `types.py` removes the asymmetry and aligns it
  with all other domain enums.

- **`LayerStatus` StrEnum added** (`types.py`) -- replaces bare `str` on
  `LayerDiffResult.status` and `LayerPair.status`. Values: `Matched`, `Added`,
  `Removed`. All construction sites in `layer_matcher.py`, `cli.py`,
  `json_report.py`, and tests updated. `StrEnum` ensures JSON serialisation
  produces the same string values as before.

- **`LayerDiffResult.layer_type` typed as `LayerType`** -- was `str` with a
  comment; is now the proper enum. `layer_type=pair.layer_type.value` call sites
  simplified to `layer_type=pair.layer_type`.

### Fixed

- **`InCu` classification false-positives** (`layer_matcher.py`) -- the previous
  check `"in" in s and "cu" in s` matched any filename containing both
  substrings (e.g. `incident_copper`, `incoming.Cu`). Replaced with
  `re.search(r"\bin\d+[._]cu\b", s)` which requires a digit immediately after
  `in` and a word boundary on both sides. Four new tests verify correct
  classification and absence of false positives.

## [0.17.0] - 2026-04-25

### Fixed

- **Cairo layer transform order** (`renderer.py`) -- reversed the three
  conditional blocks in `_render_layer` from scale->rotation->mirror to
  mirror->rotation->scale in code order. Cairo post-multiplies each call into the
  CTM, so the last call in code is the first transform applied to coordinates;
  the previous order applied transforms to coordinates as mirror->rotation->scale
  instead of the RS-274X sec.4.9-specified scale->rotation->mirror. A new test
  (`test_layer_transform_order_rotation_plus_mirror`) uses a rotation+mirror
  combination to verify the centroid of rendered pixels lands in the correct
  screen quadrant.

- **Block aperture recursion depth guard** (`renderer.py`) -- `_draw_block_flash`,
  `_render_layer`, and `_render_groups` now accept a `depth: int = 0` parameter.
  `_draw_block_flash` returns immediately when `depth >= 10`, matching the
  parser's nesting limit and preventing unbounded recursion on malformed input.
  A new test (`test_block_flash_depth_guard_no_recursion_error`) verifies that a
  15-level nested `BlockAperture` chain completes without `RecursionError`.

- **Stroke fallback line width** (`draw_ops.py`) -- `draw_net_as_stroke` now
  has explicit `case ObroundAperture()` and `case PolygonAperture()` branches
  before `case _:`. Both use `LINE_CAP_ROUND`; obround uses `min(width, height)`
  and polygon uses `outer_diameter`. The previous fallback rendered these valid
  D01 aperture types as a 25 um hairline, producing near-invisible strokes.
  Two new tests verify the corrected apertures produce > 200 lit pixels.

- **CLI `assert` -> explicit error handling** (`cli.py`) -- replaced three
  `assert` statements in `diff_cmd` that guarded against missing paths on
  added/removed/matched layers with `click.echo(..., err=True)` + `sys.exit(2)`
  checks. `assert` is stripped by `python -O`; the new checks work under all
  optimisation levels.

## [0.16.0] - 2026-04-25

### Fixed

- **Excellon integer-format coordinates** -- the parser now correctly handles
  integer fixed-decimal coordinate encoding produced by Altium, older KiCad,
  Ultiboard, and most CAM systems. A `_FormatSpec` dataclass captures the
  zero-suppression convention (`LZ` / `TZ`) and digit counts read from the
  `METRIC` / `INCH` header line; `_apply_format()` pads and inserts the decimal
  point accordingly. Explicit digit counts in the header (e.g. `METRIC,LZ,0000.0000`)
  override the defaults. Coordinates that contain a decimal point are passed
  through unchanged, preserving full compatibility with KiCad modern output.
  Files with no format header emit a `DiagnosticSeverity.Warning` and default
  to `METRIC,TZ` 3.3.
- 13 new tests in `tests/test_excellon_parser.py` covering `_apply_format` unit
  tests (decimal pass-through, METRIC LZ 3.3, INCH TZ 2.4, negative coords, zero)
  and end-to-end round-trips (inline content and two new fixtures:
  `tests/fixtures/drill-metric-lz.drl`, `tests/fixtures/drill-inch-tz.drl`).

## [0.15.0] - 2026-04-25

### Changed

- **License changed from AGPL-3.0 to Apache-2.0** so the tool can be
  used commercially without copyleft obligations. (Landed immediately
  before this version's other changes; recorded here for completeness.)

- **Domain model rename** -- `Net` renamed to `DrawOp` and `NetState` renamed to `CoordState`
  throughout the codebase. The term "net" belongs to EDA net-list semantics; the IR types
  represent drawing primitives and coordinate-system snapshots, not electrical nets.
  - `ParsedImage.nets` -> `draw_ops`
  - `ParsedImage.net_states` -> `coord_states`
  - `BlockAperture.nets` -> `draw_ops`
    All public and internal references updated; import order re-sorted (ruff I001).

## [0.14.0] - 2026-04-25

### Added

- **Block aperture parsing** -- `%ABD<n>*%` / `%AB*%` extended commands now fully handled in
  `gerber_state.py`. The parser maintains a nested block stack (max depth 10) that redirects
  net emission, layer state, and the bounding box into a `BlockAperture` while the block is
  open; on close the completed aperture is registered into the parent aperture dict. Apertures
  defined before the block open are accessible inside it via a shallow copy of the parent dict.
- `layers: list[LayerState]` field added to `BlockAperture` to capture the block's own
  polarity/layer stack -- matching the reference JS implementation.
- **`BlockFlash` rendering** -- `_draw_block_flash()` helper in `renderer.py` synthesises a
  temporary `ParsedImage` from the block's captured nets/apertures/layers and recursively runs
  the compile -> render pipeline, translating to the flash position via `ctx.translate(x, y)`.
- **Edge-case hardening**:
  - Empty gerber (no geometry) no longer raises; produces a default centred viewport.
  - Boards with coordinates entirely in negative space render and center correctly.
  - Step-and-repeat correctness verified -- 2x2 SR produces measurably more lit pixels than a
    single instance.
- 17 tests in `tests/test_block_aperture.py` covering: parse registration, net capture, parent
  isolation, layer capture, parent-aperture inheritance, invalid D-code warnings, stray close
  warning, `BlockFlash` compile path, render output, empty block, empty gerber viewport, negative
  coordinate centering, and step-and-repeat pixel count.
- `README.md` -- full CLI reference for all three subcommands (`parse`, `render`, `diff`) with
  option tables, overlay colour-scheme description, JSON report schema, and development commands.

### Fixed

- `test_negative_coordinate_viewport` assertion corrected -- `pan_y` is legitimately negative
  for boards in the negative-Y half-plane; test now validates the correct invariant (board
  centre maps to canvas centre) rather than the sign of `pan_y`.

## [0.13.0] - 2026-04-25

### Added

- **`diff` CLI subcommand** (`gerberdiff diff BEFORE_DIR AFTER_DIR`) with options:
  - `--layer NAME` (repeatable) -- restrict diff to named layers
  - `--width` / `--height` -- canvas dimensions (default 2048)
  - `--min-pixels` -- minimum pixel count for a reported region (default 4)
  - `--merge-tolerance` -- region merge padding in inches (default 0.05)
  - `--out-json PATH` -- write JSON diff report
  - `--out-png DIR` -- write per-layer overlay PNGs
  - `--overwrite` -- allow replacing existing output files
  - `--png-show-common` -- shade unchanged geometry grey in PNG overlays
  - `--align-offset X,Y` -- translate board B by (X, Y) inches before diffing
  - `--fail-on-diff` -- exit 1 if any changes detected
  - `--quiet` / `--verbose`
  - Exit codes: 0 = no diff (or diff without `--fail-on-diff`), 1 = diff found with
    `--fail-on-diff`, 2 = parse/IO error.
- **`gerberdiff/export/json_report.py`** -- `build_report(diff_result) -> dict` and
  `write_report(diff_result, path, overwrite)` producing a versioned JSON schema (version: 1)
  with summary (`changed_layers`, `total_regions`, `has_changes`) and per-layer region detail.
  Raises `FileExistsError` when the target exists and `overwrite=False`. Parent directories
  created automatically.
- **`gerberdiff/export/png_export.py`** -- `build_overlay_png(arr_a, arr_b, xor, path, ...)`.
  Colour scheme (BGRA ARGB32): removed -> red `[0,0,255,255]`, added -> green `[0,255,0,255]`,
  changed (both non-zero, different value) -> yellow `[0,255,255,255]`, common (opt-in) -> grey
  `[128,128,128,255]`. Written via `cairocffi.ImageSurface.create_for_data`.
- `DiffResult` and `LayerDiffResult` types added to `gerberdiff/types.py` (`has_changes` is a
  stored field, not a property, so added/removed layers correctly drive `has_changes=True`
  regardless of pixel count).
- 14 tests in `tests/test_json_report.py` and 8 tests in `tests/test_png_export.py`.
- 11 fixture-based integration tests in `tests/test_cli_diff.py` (guarded with
  `pytest.mark.skipif` when fixtures are absent).

## [0.12.0] - 2026-04-25

### Added

- **`gerberdiff/diff/layer_matcher.py`** -- `match_layers(before_dir, after_dir) -> list[LayerPair]`
  pairs layers by file stem across two directories. Unmatched files are reported as
  `status="added"` or `status="removed"`. Results are sorted by a canonical
  `_LAYER_TYPE_ORDER` (FCu -> BCu -> inner Cu -> masks -> paste -> silk -> edge cuts -> drill ->
  unknown).
- `LayerType` StrEnum with 14 values: `FCu`, `BCu`, `InCu`, `FMask`, `BMask`, `FPaste`,
  `BPaste`, `FSilk`, `BSilk`, `EdgeCuts`, `NPTH`, `PTH`, `Drill`, `Unknown`.
- `LayerPair` dataclass: `name`, `before_path`, `after_path`, `layer_type`, `status`.
- `classify_layer(path) -> LayerType` -- classifies a single file by name/suffix heuristics.
- 29 tests in `tests/test_layer_matcher.py`.
- `scipy-stubs>=1.17.1.4` added to the `[dependency-groups].dev` group.

## [0.11.0] - 2026-04-25

### Added

- **`gerberdiff/diff/diff_engine.py`** -- pixel-based diff pipeline:
  1. Renders both images to a shared viewport (`merge_bounding_boxes` + `compute_viewport`).
  2. XORs RGB channels to produce a boolean change mask.
  3. `_ccl_and_extract()` -- `scipy.ndimage.label` (4-connectivity) -> `find_objects` ->
     `center_of_mass` -> `list[Region]` with world-space (inch) centroid and bounding box.
  4. `merge_overlapping_regions()` -- iterative weighted-centroid merge within a tolerance.
- `SingleLayerDiff` dataclass: `arr_a`, `arr_b`, `xor`, `regions`, `viewport`,
  `changed_pixel_count`, `total_pixel_count`.
- `compute_diff(image_a, image_b, width, height, alignment_offset, min_pixel_count,
merge_tolerance) -> SingleLayerDiff`.
- `Region`, `LayerDiffResult`, `DiffResult` types added to `gerberdiff/types.py`.
- `coordinate_offset: tuple[float, float] | None` parameter added to `render_to_surface()`
  and `render_to_numpy()` -- applied as `ctx.translate()` after viewport scale, enabling
  panel-offset alignment.
- 17 tests in `tests/test_diff_engine.py`.

## [0.10.0] - 2026-04-25

### Added

- **`render` CLI subcommand** (`gerberdiff render FILE --out-png PATH`) with options:
  `--width`, `--height`, `--overwrite`, `--quiet`, `--verbose`. Accepts both Gerber and
  Excellon files (auto-detected by suffix). Prints render timing under `--verbose`.
- Memory warning for canvases exceeding 16 777 216 pixels (~64 MB) -- non-blocking advisory
  message to stderr.
- 9 tests in `tests/test_cli_render.py`.

### Changed

- **`scipy` promoted to core required dependency** (`scipy>=1.10` in `[project].dependencies`).
  Previously treated as an optional extra; made core because `diff_engine.py` requires
  `scipy.ndimage` and there is no meaningful fallback.

## [0.9.0] - 2026-04-25

### Added

- **`gerberdiff/render/compiled_render.py`** -- single-pass compile stage that walks the flat
  nets list and groups operations into typed batch objects:
  - `FlashBatch` -- simple flashes sharing one aperture (no hole, no macro/block)
  - `StrokeBatch` -- D01 strokes sharing one aperture
  - `RegionGroup` -- G36/G37 region fill
  - `HoledFlash` -- flash for an aperture with a punch-through hole
  - `MacroFlash` -- flash for a macro aperture (one per net)
  - `BlockFlash` -- flash for a block aperture (one per net; rendered in 0.14.0)
  - `CompiledLayer`, `CompiledRender` containers.
- **`gerberdiff/render/renderer.py`** -- two-pass Cairo rasteriser:
  - `render_to_surface(parsed_image, viewport, draw_color, coordinate_offset)
-> cairo.ImageSurface`
  - `render_to_numpy(parsed_image, viewport, draw_color, coordinate_offset)
-> np.ndarray` (shape `(H, W, 4)` uint8, BGRA; `.copy()` called to detach from Cairo
    buffer before returning)
  - Polarity compositing via `OPERATOR_OVER` (dark) / `OPERATOR_DEST_OUT` (clear).
  - Per-layer transforms: scale, rotation, mirror.
  - Step-and-repeat rendered by nested `ctx.translate` loops.
- 14 tests in `tests/test_renderer.py`.

## [0.8.0] - 2026-04-25

### Added

- **`gerberdiff/render/macro_renderer.py`** -- all 7 RS-274X aperture macro primitive types:
  - `1` -- Circle
  - `20` -- Vector line
  - `21` -- Center line
  - `4` -- Outline
  - `5` -- Polygon
  - `6` -- Moire
  - `7` -- Thermal
- `draw_macro_flash(ctx, x, y, aperture: MacroAperture)` -- evaluates macro expressions,
  renders each primitive with correct rotation and polarity into the current Cairo context.
- `compute_macro_bounding_radius(aperture: MacroAperture) -> float` -- conservative radius
  estimate used for bounding-box expansion.
- 14 tests in `tests/test_macro_renderer.py`.

## [0.7.0] - 2026-04-25

### Added

- **`gerberdiff/render/viewport.py`**:
  - `Viewport` dataclass (`width`, `height`, `pan_x`, `pan_y`, `zoom`).
  - `compute_viewport(bbox, width, height) -> Viewport` -- fits the bounding box with a 10%
    margin, Y-flipped so Gerber's mathematical Y-up maps to screen Y-down.
  - `merge_bounding_boxes(a, b) -> BoundingBox` -- axis-aligned union of two boxes.
  - `screen_to_world(px, py, vp) -> tuple[float, float]` -- inverse viewport transform.
- **`gerberdiff/render/draw_ops.py`**:
  - `draw_arc_path(ctx, arc_segment, start_x, start_y)` -- draws a Cairo arc path from a
    resolved `ArcSegment`.
  - `draw_net_segment_in_region(ctx, net)` -- adds a net's segment to an open region path.
  - `draw_net_as_stroke(ctx, net, aperture)` -- strokes a D01 net with aperture-derived line
    width and cap style.
  - `draw_flash(ctx, net, aperture)` -- fills/strokes a D03 flash for all standard aperture
    shapes (circle, rectangle, obround, polygon).
- 9 tests in `tests/test_viewport.py` and 13 tests in `tests/test_draw_ops.py`.

## [0.6.0] - 2026-04-25

### Added

- **`gerberdiff/parse/excellon_parser.py`** -- Excellon NC drill format parser. Supports tool
  definitions (`T<n>C<dia>`), drill hits (D03 / no D-code with coordinates), routed slots
  (G00 move + G01 linear route), metric/imperial unit modes, and leading/trailing zero
  suppression. Emits `ParsedImage` with the same IR as the Gerber parser.
- **`parse` CLI subcommand** (`gerberdiff parse FILE`) with options: `--dump-ir` (JSON
  summary to stdout), `--quiet`, `--verbose`. Auto-detects Gerber vs. Excellon by file suffix.
  Exit code 2 on parse errors.
- 8 tests in `tests/test_excellon_parser.py` and 6 tests in `tests/test_cli_parse.py`.

## [0.5.0] - 2026-04-25

### Added

- **`gerberdiff/parse/gerber_state.py`** -- full RS-274X stateful parser:
  - Format statement (`%FS...%`) and unit mode (`%MO...%`)
  - All aperture definitions via `parse_aperture_definition` (phases 3-4)
  - Macro definitions (`%AM...%`) collected and parsed via `parse_macro_body`
  - Layer polarity (`%LP...%`), mirror (`%LM...%`), rotation (`%LR...%`), scale (`%LS...%`), name
    (`%LN...%`)
  - Step-and-repeat (`%SR...%`) with `SRX<n>Y<n>I<step>J<step>` syntax
  - Absolute / incremental coordinate modes (G90/G91)
  - Arc modes single-quadrant G74 / multi-quadrant G75
  - Region fill G36/G37
  - Object and aperture attributes (`%TO...%`, `%TA...%`, `%TD...%`, `%TF...%`)
  - Deprecated codes (G54/55/70/71, `%IA...%`, `%AS...%`, `%MI...%`, `%OF...%`, `%SF...%`) handled
    gracefully
  - `parse_gerber(content, source_path) -> ParsedImage`
- 12 tests in `tests/test_gerber_state.py`.

## [0.4.0] - 2026-04-25

### Added

- **`gerberdiff/parse/arc_math.py`** -- geometry helpers for both arc modes:
  - `compute_arc_single_quadrant(sx, sy, ex, ey, i, j, clockwise) -> ArcSegment | None`
  - `compute_arc_multi_quadrant(sx, sy, ex, ey, i, j, clockwise) -> ArcSegment | None`
- **`gerberdiff/parse/macro_parser.py`** -- RS-274X aperture macro parser and evaluator:
  - Expression AST with literal, variable (`$n`), binary operators, and unary minus nodes.
  - `parse_macro_body(name, body) -> MacroDef`
  - All 7 primitive types parsed into `MacroPrimitive` dataclasses.
  - `evaluate_macro_expression(node, params) -> float`
- `MacroDef`, `MacroPrimitive`, `MacroExpression` type hierarchy.
- 8 tests in `tests/test_arc_math.py` and 19 tests in `tests/test_macro_parser.py`.

## [0.3.0] - 2026-04-25

### Added

- **`gerberdiff/parse/tokenizer.py`** -- RS-274X tokenizer:
  - `TokenType` StrEnum: `GCode`, `DCode`, `Coordinate`, `EndOfBlock`, `Extended`, `EndOfFile`,
    `Unknown`.
  - `Token` dataclass: `type`, `raw`, `numeric_value`, `line`.
  - `tokenize_gerber(content) -> Iterator[Token]`
- **`gerberdiff/parse/gerber_parser.py`** -- stateless gerber parser utilities:
  - `FormatStatement` dataclass.
  - `parse_format_statement(body) -> FormatStatement | None`
  - `parse_aperture_definition(body, unit, macro_map) -> tuple[int, Aperture] | None` --
    handles circle, rectangle, obround, polygon, and macro apertures with optional hole
    diameters and unit scaling (inch -> mm).
  - `convert_coordinate(raw_int, raw_str, int_digits, dec_digits, zero_omission, unit) -> float`
    converting raw token values to inches.
- 13 tests in `tests/test_tokenizer.py` and 17 tests in `tests/test_gerber_parser.py`.

## [0.2.0] - 2026-04-25

### Added

- **`gerberdiff/types.py`** -- complete intermediate representation (IR) type system:
  - Enums (all `StrEnum`): `ApertureType`, `ApertureState`, `InterpolationMode`, `Polarity`,
    `MirrorState`, `UnitType`, `ZeroOmission`, `CoordinateMode`, `DiagnosticSeverity`.
  - Geometric primitives: `ArcSegment`, `BoundingBox` (with `expand()` and `is_valid`).
  - Drawing state: `StepAndRepeat`, `LayerState`, `NetState`, `Net`, `Diagnostic`.
  - Aperture types: `CircleAperture`, `RectangleAperture`, `ObroundAperture`,
    `PolygonAperture`, `MacroAperture`, `BlockAperture`.
  - `Aperture` union `TypeAlias`.
  - `ParsedImage` top-level IR container.
- 11 tests in `tests/test_types.py`.

## [0.1.0] - 2026-04-24

### Added

- Package scaffold: `pyproject.toml` (hatchling build), `uv.lock`, `gerberdiff/__init__.py`
  with `__version__ = "0.1.0"`.
- CLI entry point `gerberdiff = "gerberdiff.cli:cli"` (stub group with version option).
- Subpackage directories with `__init__.py`: `parse/`, `render/`, `diff/`, `export/`.
- Core runtime dependencies: `click>=8`, `numpy>=1.24`, `cairocffi>=1.6`.
- Optional extra `gerberdiff[rich]` for `rich>=13`.
- Dev toolchain in `[dependency-groups].dev`: `pytest>=8`, `pytest-cov>=5`, `ruff>=0.4`,
  `mypy>=1.10`.
- Ruff rules: E, F, I, UP, B, C4, RUF; ignores E501. `known-first-party = ["gerberdiff"]`.
- mypy `strict=true`, `warn_unused_ignores=true`, `cairocffi.*` override for missing stubs.
- 2 smoke tests in `tests/test_scaffold.py`.

[Unreleased]: https://github.com/CameronBrooks11/gerberdiff/compare/v0.29.1...HEAD
[0.29.1]: https://github.com/CameronBrooks11/gerberdiff/compare/v0.29.0...v0.29.1
[0.29.0]: https://github.com/CameronBrooks11/gerberdiff/compare/9ffd4c8f...v0.29.0
[0.28.0]: https://github.com/CameronBrooks11/gerberdiff/compare/b6b6b98d...9ffd4c8f
[0.27.0]: https://github.com/CameronBrooks11/gerberdiff/compare/963eb957...b6b6b98d
[0.26.0]: https://github.com/CameronBrooks11/gerberdiff/compare/6162e435...963eb957
[0.25.0]: https://github.com/CameronBrooks11/gerberdiff/compare/e2519ec8...6162e435
[0.24.0]: https://github.com/CameronBrooks11/gerberdiff/compare/91c154d4...e2519ec8
[0.23.0]: https://github.com/CameronBrooks11/gerberdiff/compare/458734f9...91c154d4
[0.22.0]: https://github.com/CameronBrooks11/gerberdiff/compare/1c96a7b8...458734f9
[0.21.0]: https://github.com/CameronBrooks11/gerberdiff/compare/4d1201fe...1c96a7b8
[0.20.0]: https://github.com/CameronBrooks11/gerberdiff/compare/ba9a5015...4d1201fe
[0.19.0]: https://github.com/CameronBrooks11/gerberdiff/compare/c502171a...ba9a5015
[0.18.0]: https://github.com/CameronBrooks11/gerberdiff/compare/10f8f392...c502171a
[0.17.0]: https://github.com/CameronBrooks11/gerberdiff/compare/b04813ea...10f8f392
[0.16.0]: https://github.com/CameronBrooks11/gerberdiff/compare/3044033b...b04813ea
[0.15.0]: https://github.com/CameronBrooks11/gerberdiff/compare/9b4e3401...3044033b
[0.14.0]: https://github.com/CameronBrooks11/gerberdiff/compare/1a399ea2...9b4e3401
[0.13.0]: https://github.com/CameronBrooks11/gerberdiff/compare/c0672ea8...1a399ea2
[0.12.0]: https://github.com/CameronBrooks11/gerberdiff/compare/1bbfb235...c0672ea8
[0.11.0]: https://github.com/CameronBrooks11/gerberdiff/compare/2d1573ad...1bbfb235
[0.10.0]: https://github.com/CameronBrooks11/gerberdiff/compare/6691b195...2d1573ad
[0.9.0]: https://github.com/CameronBrooks11/gerberdiff/compare/2e944edc...6691b195
[0.8.0]: https://github.com/CameronBrooks11/gerberdiff/compare/46b463de...2e944edc
[0.7.0]: https://github.com/CameronBrooks11/gerberdiff/compare/5b9212fa...46b463de
[0.6.0]: https://github.com/CameronBrooks11/gerberdiff/compare/e12ff13f...5b9212fa
[0.5.0]: https://github.com/CameronBrooks11/gerberdiff/compare/6330d0cb...e12ff13f
[0.4.0]: https://github.com/CameronBrooks11/gerberdiff/compare/f63a51a3...6330d0cb
[0.3.0]: https://github.com/CameronBrooks11/gerberdiff/compare/3f1d1909...f63a51a3
[0.2.0]: https://github.com/CameronBrooks11/gerberdiff/compare/674251dd...3f1d1909
[0.1.0]: https://github.com/CameronBrooks11/gerberdiff/compare/2eeb692...674251dd
