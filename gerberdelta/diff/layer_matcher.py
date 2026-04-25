"""Layer matcher: pair before/after files by stem and classify by type.

Algorithm
---------
1. List all Gerber/Excellon files in *before_dir* and *after_dir*.
2. Exact stem match -> status ``"matched"``.
3. Unmatched in *before_dir* only -> status ``"removed"``.
4. Unmatched in *after_dir* only -> status ``"added"``.

Layer type detection uses suffix and stem patterns:

Gerber extensions:  ``.gbr .ger .gtl .gbl .gts .gbs .gto .gbo .gtp .gbp .gm1``
Excellon extensions: ``.drl .exc .xln .ncd``

Stem keyword matching (case-insensitive, substring) determines ``LayerType``:
- ``f.cu`` or ``front copper`` -> ``FCu``
- ``b.cu`` or ``back copper``  -> ``BCu``
- ``in1.cu`` ... ``in4.cu``     -> ``InCu``
- ``f.mask`` / ``b.mask``     -> ``FMask`` / ``BMask``
- ``f.paste`` / ``b.paste``   -> ``FPaste`` / ``BPaste``
- ``f.silks`` / ``f.silk``    -> ``FSilk``
- ``b.silks`` / ``b.silk``    -> ``BSilk``
- ``edge.cuts`` / ``edgecuts``-> ``EdgeCuts``
- ``npth``                    -> ``NPTH``
- ``pth`` (but not ``npth``)  -> ``PTH``
- Excellon extension but no keyword match -> ``Drill``
- Anything else               -> ``Unknown``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gerberdelta.types import LayerStatus, LayerType

_GERBER_SUFFIXES = frozenset(
    {
        ".gbr",
        ".ger",
        ".gtl",
        ".gbl",  # top/bottom copper (legacy)
        ".gts",
        ".gbs",  # top/bottom solder mask
        ".gto",
        ".gbo",  # top/bottom silkscreen
        ".gtp",
        ".gbp",  # top/bottom paste
        ".gm1",  # mechanical/edge cuts (legacy)
    }
)

EXCELLON_SUFFIXES = frozenset({".drl", ".exc", ".xln", ".ncd"})

_LAYER_SUFFIXES = _GERBER_SUFFIXES | EXCELLON_SUFFIXES


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class LayerPair:
    """A matched, added, or removed layer."""

    name: str  # display name = common stem (or bare filename)
    before_path: Path | None  # None -> layer was added in after/
    after_path: Path | None  # None -> layer was removed from before/
    layer_type: LayerType
    status: LayerStatus  # Matched | Added | Removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_layers(before_dir: Path, after_dir: Path) -> list[LayerPair]:
    """Match layer files between *before_dir* and *after_dir*.

    Returns a list of :class:`LayerPair` objects sorted by layer type order
    then alphabetically by name.
    """
    before_files = _index_dir(before_dir)
    after_files = _index_dir(after_dir)

    pairs: list[LayerPair] = []

    all_stems = sorted(set(before_files) | set(after_files))
    for stem in all_stems:
        b_path = before_files.get(stem)
        a_path = after_files.get(stem)

        if b_path is not None and a_path is not None:
            status = LayerStatus.Matched
        elif b_path is not None:
            status = LayerStatus.Removed
        else:
            status = LayerStatus.Added

        # Determine layer type from whichever path is available.
        sample_path = b_path if b_path is not None else a_path
        ltype = _classify(stem, sample_path)  # type: ignore[arg-type]

        pairs.append(
            LayerPair(
                name=stem,
                before_path=b_path,
                after_path=a_path,
                layer_type=ltype,
                status=status,
            )
        )

    pairs.sort(key=lambda p: (_LAYER_TYPE_ORDER.get(p.layer_type, 99), p.name))
    return pairs


def classify_layer(path: Path) -> LayerType:
    """Classify a single file's layer type by name."""
    return _classify(path.stem, path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _index_dir(directory: Path) -> dict[str, Path]:
    """Return a mapping of stem -> Path for all layer files in *directory*."""
    result: dict[str, Path] = {}
    if not directory.is_dir():
        return result
    for p in directory.iterdir():
        if p.suffix.lower() in _LAYER_SUFFIXES:
            result[p.stem] = p
    return result


def _classify(stem: str, path: Path) -> LayerType:
    """Return the :class:`LayerType` for a file with the given *stem*."""
    s = stem.lower()
    ext = path.suffix.lower()

    # Order matters: NPTH must be checked before PTH.
    if "npth" in s:
        return LayerType.NPTH
    if "pth" in s:
        return LayerType.PTH
    if "f.cu" in s or "f_cu" in s or "front_copper" in s or "front copper" in s:
        return LayerType.FCu
    if "b.cu" in s or "b_cu" in s or "back_copper" in s or "back copper" in s:
        return LayerType.BCu
    if re.search(r"\bin\d+[._]cu\b", s):
        return LayerType.InCu
    if "f.mask" in s or "f_mask" in s:
        return LayerType.FMask
    if "b.mask" in s or "b_mask" in s:
        return LayerType.BMask
    if "f.paste" in s or "f_paste" in s:
        return LayerType.FPaste
    if "b.paste" in s or "b_paste" in s:
        return LayerType.BPaste
    if "f.silks" in s or "f_silks" in s or "f.silk" in s or "f_silk" in s:
        return LayerType.FSilk
    if "b.silks" in s or "b_silks" in s or "b.silk" in s or "b_silk" in s:
        return LayerType.BSilk
    if "edge.cuts" in s or "edge_cuts" in s or "edgecuts" in s:
        return LayerType.EdgeCuts
    # Legacy top/bottom copper by suffix
    if ext in (".gtl", ".gbl"):
        return LayerType.FCu if ext == ".gtl" else LayerType.BCu
    # Legacy mask / silkscreen / paste by suffix
    if ext in (".gts", ".gbs"):
        return LayerType.FMask if ext == ".gts" else LayerType.BMask
    if ext in (".gto", ".gbo"):
        return LayerType.FSilk if ext == ".gto" else LayerType.BSilk
    if ext in (".gtp", ".gbp"):
        return LayerType.FPaste if ext == ".gtp" else LayerType.BPaste
    # Drill files with no keyword match
    if ext in EXCELLON_SUFFIXES:
        return LayerType.Drill
    return LayerType.Unknown


# Display / sort order for layer types (signal layers first, then mechanical).
_LAYER_TYPE_ORDER: dict[LayerType, int] = {
    LayerType.FCu: 0,
    LayerType.InCu: 1,
    LayerType.BCu: 2,
    LayerType.FMask: 3,
    LayerType.BMask: 4,
    LayerType.FPaste: 5,
    LayerType.BPaste: 6,
    LayerType.FSilk: 7,
    LayerType.BSilk: 8,
    LayerType.EdgeCuts: 9,
    LayerType.NPTH: 10,
    LayerType.PTH: 11,
    LayerType.Drill: 12,
    LayerType.Unknown: 13,
}
