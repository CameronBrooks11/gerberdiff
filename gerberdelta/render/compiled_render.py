"""Compile pass: group ParsedImage nets into batched draw groups.

The compile pass walks the flat nets list once and emits ``CompiledRender``
-- a list of ``CompiledLayer`` objects each holding ``CompiledGroup`` items
that the renderer can dispatch without re-inspecting every net.

Batching rules
--------------
* ``ApertureState.Flash`` + simple aperture (no hole) -> ``FlashBatch``
  (grouped by aperture_code)
* ``ApertureState.Flash`` + holed aperture -> ``HoledFlash`` (one per net)
* ``ApertureState.Flash`` + ``MacroAperture`` -> ``MacroFlash`` (one per net)
* ``ApertureState.Flash`` + ``BlockAperture`` -> ``BlockFlash`` (one per net)
* ``ApertureState.On`` -> ``StrokeBatch`` (grouped by aperture_code)
* ``RegionFill`` -> ``RegionGroup``
* ``ApertureState.Off`` flushes any open stroke batch.

Layer boundaries flush all open batches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from gerberdelta.types import (
    ApertureState,
    BlockAperture,
    CircleAperture,
    DrawOp,
    MacroAperture,
    MirrorState,
    ObroundAperture,
    ParsedImage,
    Polarity,
    PolygonAperture,
    RectangleAperture,
    RegionFill,
    StepAndRepeat,
)

# ---------------------------------------------------------------------------
# Group dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FlashBatch:
    """Simple flashes sharing one aperture (no hole, no macro/block)."""

    kind: Literal["flash_batch"] = field(default="flash_batch", init=False)
    aperture_code: int = 0
    nets: list[DrawOp] = field(default_factory=list)


@dataclass
class StrokeBatch:
    """D01 strokes sharing one aperture."""

    kind: Literal["stroke_batch"] = field(default="stroke_batch", init=False)
    aperture_code: int = 0
    nets: list[DrawOp] = field(default_factory=list)


@dataclass
class RegionGroup:
    """Contiguous region fill bounded by G36/G37 markers."""

    kind: Literal["region_group"] = field(default="region_group", init=False)
    nets: list[DrawOp] = field(default_factory=list)


@dataclass
class HoledFlash:
    """Single flash for an aperture with a punch-through hole."""

    kind: Literal["holed_flash"] = field(default="holed_flash", init=False)
    aperture_code: int = 0
    net: DrawOp | None = None


@dataclass
class MacroFlash:
    """Single flash for a macro aperture."""

    kind: Literal["macro_flash"] = field(default="macro_flash", init=False)
    aperture_code: int = 0
    net: DrawOp | None = None


@dataclass
class BlockFlash:
    """Single flash for a block aperture (rendered in Phase 14)."""

    kind: Literal["block_flash"] = field(default="block_flash", init=False)
    aperture_code: int = 0
    net: DrawOp | None = None


CompiledGroup = FlashBatch | StrokeBatch | RegionGroup | HoledFlash | MacroFlash | BlockFlash


# ---------------------------------------------------------------------------
# Compiled layer / render containers
# ---------------------------------------------------------------------------


@dataclass
class CompiledLayer:
    """One polarity layer with batched draw groups."""

    layer_index: int = 0
    step_and_repeat: StepAndRepeat = field(default_factory=StepAndRepeat)
    polarity: Polarity = Polarity.Dark
    mirror: MirrorState = MirrorState.None_
    rotation: float = 0.0
    scale: float = 1.0
    groups: list[CompiledGroup] = field(default_factory=list)


@dataclass
class CompiledRender:
    """Output of the compile pass, consumed by the renderer."""

    layers: list[CompiledLayer] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Compile pass
# ---------------------------------------------------------------------------


def compile_render(parsed_image: ParsedImage) -> CompiledRender:
    """Walk parsed_image.nets once and produce a ``CompiledRender``.

    The resulting structure is layer-ordered and batch-merged so the renderer
    can operate without any aperture-classification logic.
    """
    compiled = CompiledRender()

    # Build a CompiledLayer for every LayerState in the parsed image.
    layer_map: dict[int, CompiledLayer] = {}
    for i, ls in enumerate(parsed_image.layers):
        cl = CompiledLayer(
            layer_index=i,
            step_and_repeat=ls.step_and_repeat,
            polarity=ls.polarity,
            mirror=ls.mirror,
            rotation=ls.rotation,
            scale=ls.scale,
        )
        layer_map[i] = cl
        compiled.layers.append(cl)

    # Mutable batching state (closed over by the flush helpers below).
    pending_flash: FlashBatch | None = None
    pending_stroke: StrokeBatch | None = None
    # The layer that owns the two pending batches.
    batch_layer: CompiledLayer | None = None

    def _flush_flash() -> None:
        nonlocal pending_flash
        if pending_flash is not None and batch_layer is not None:
            batch_layer.groups.append(pending_flash)
        pending_flash = None

    def _flush_stroke() -> None:
        nonlocal pending_stroke
        if pending_stroke is not None and batch_layer is not None:
            batch_layer.groups.append(pending_stroke)
        pending_stroke = None

    def _switch_layer(new_layer: CompiledLayer) -> None:
        nonlocal batch_layer
        _flush_flash()
        _flush_stroke()
        batch_layer = new_layer

    for item in parsed_image.draw_ops:
        if isinstance(item, RegionFill):
            layer = layer_map.get(item.layer_index)
            if layer is not None:
                _flush_flash()
                _flush_stroke()
                if item.segments:
                    layer.groups.append(RegionGroup(nets=list(item.segments)))
            continue

        net = item
        layer = layer_map.get(net.layer_index)
        if layer is None:
            continue

        # Flush open batches whenever the active layer changes.
        if batch_layer is not layer:
            _switch_layer(layer)

        # ---- Flash (D03) ----
        if net.aperture_state == ApertureState.Flash:
            _flush_stroke()
            ap = parsed_image.apertures.get(net.aperture_index)
            if isinstance(ap, MacroAperture):
                _flush_flash()
                layer.groups.append(MacroFlash(aperture_code=net.aperture_index, net=net))
            elif isinstance(ap, BlockAperture):
                _flush_flash()
                layer.groups.append(BlockFlash(aperture_code=net.aperture_index, net=net))
            elif (
                isinstance(
                    ap, (CircleAperture, RectangleAperture, ObroundAperture, PolygonAperture)
                )
                and ap.hole_diameter is not None
            ):
                _flush_flash()
                layer.groups.append(HoledFlash(aperture_code=net.aperture_index, net=net))
            else:
                # Simple flash -- batch by aperture_code.
                if pending_flash is None or pending_flash.aperture_code != net.aperture_index:
                    _flush_flash()
                    pending_flash = FlashBatch(aperture_code=net.aperture_index)
                pending_flash.nets.append(net)

        # ---- On (D01 draw) ----
        elif net.aperture_state == ApertureState.On:
            _flush_flash()
            if pending_stroke is None or pending_stroke.aperture_code != net.aperture_index:
                _flush_stroke()
                pending_stroke = StrokeBatch(aperture_code=net.aperture_index)
            pending_stroke.nets.append(net)

        # ---- Off (D02 move) -- just flush open batches ----
        elif net.aperture_state == ApertureState.Off:
            _flush_flash()
            _flush_stroke()

    # Final flush.
    _flush_flash()
    _flush_stroke()

    return compiled
