"""Change attribution: match expanded ops between revisions and classify.

Three-stage algorithm:

1. **Exact cancellation** -- ops with identical content signatures (same
   world geometry, polarity, kind) are unchanged.  This typically covers
   the vast majority of ops and costs only hashing.
2. **Gated geometric matching** -- remaining ops are pooled by (kind,
   polarity) and matched A->B by centroid proximity within *gate_radius*
   (KD-tree candidates, globally-greedy by distance for determinism).
3. **Classification** of each matched pair:

   - same dims, offset >  move_tol  -> ``moved``
   - same dims, offset <= move_tol  -> unchanged (float noise)
   - dims changed                   -> ``resized`` (dx/dy still recorded)

   "Same dims" = identical aperture signature *and* relative area delta
   within *area_tol* (the area check distinguishes a stretched stroke from
   a translated one).

Unmatched A-ops are ``removed``; unmatched B-ops are ``added``.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from gerberdiff.geometry.layer_geometry import ExpandedOp
from gerberdiff.geometry.types import ChangeKind

# Classification kinds (public result vocabulary).
KIND_ADDED: ChangeKind = "added"
KIND_REMOVED: ChangeKind = "removed"
KIND_MOVED: ChangeKind = "moved"
KIND_RESIZED: ChangeKind = "resized"


@dataclass
class OpChange:
    """One attributed change between revisions (engine-internal record)."""

    kind: ChangeKind
    before: ExpandedOp | None
    after: ExpandedOp | None
    dx: float = 0.0  # inches (after - before), 0 when one side is absent
    dy: float = 0.0


@dataclass
class Partition:
    """Result of exact-cancellation matching between two op lists."""

    unchanged_a: list[ExpandedOp]
    unchanged_b: list[ExpandedOp]
    a_only: list[ExpandedOp]
    b_only: list[ExpandedOp]


def partition_unchanged(
    a_ops: list[ExpandedOp],
    b_ops: list[ExpandedOp],
) -> Partition:
    """Multiset-match ops by content signature (stage 1)."""
    counts_a = Counter(op.signature for op in a_ops)
    counts_b = Counter(op.signature for op in b_ops)
    shared = counts_a & counts_b

    def _split(
        ops: list[ExpandedOp], budget: Counter[str]
    ) -> tuple[list[ExpandedOp], list[ExpandedOp]]:
        unchanged: list[ExpandedOp] = []
        only: list[ExpandedOp] = []
        for op in ops:
            if budget[op.signature] > 0:
                budget[op.signature] -= 1
                unchanged.append(op)
            else:
                only.append(op)
        return unchanged, only

    unchanged_a, a_only = _split(a_ops, Counter(shared))
    unchanged_b, b_only = _split(b_ops, Counter(shared))
    return Partition(unchanged_a=unchanged_a, unchanged_b=unchanged_b, a_only=a_only, b_only=b_only)


def attribute_changes(
    parts: Partition,
    *,
    move_tol: float,
    gate_radius: float,
    area_tol: float,
) -> tuple[list[OpChange], int]:
    """Stages 2+3: match and classify the non-identical ops.

    All distances in inches.  Returns ``(changes, unchanged_count)`` where
    *unchanged_count* includes both exact-signature matches and matched
    pairs whose offset fell below *move_tol*.
    """
    unchanged_count = len(parts.unchanged_a)
    changes: list[OpChange] = []

    matched_a: set[int] = set()
    matched_b: set[int] = set()

    # Pool by (kind, polarity): a flash never matches a stroke, dark never
    # matches clear.
    pools: dict[tuple[str, str], tuple[list[int], list[int]]] = {}
    for i, op in enumerate(parts.a_only):
        pools.setdefault((op.kind, op.polarity.value), ([], []))[0].append(i)
    for j, op in enumerate(parts.b_only):
        pools.setdefault((op.kind, op.polarity.value), ([], []))[1].append(j)

    for a_idx, b_idx in pools.values():
        if not a_idx or not b_idx:
            continue
        pairs = _match_pool(parts, a_idx, b_idx, gate_radius, matched_a, matched_b)
        for a_op, b_op in pairs:
            dx = b_op.centroid_x - a_op.centroid_x
            dy = b_op.centroid_y - a_op.centroid_y
            offset = math.hypot(dx, dy)
            if _dims_same(a_op, b_op, area_tol):
                if offset <= move_tol:
                    unchanged_count += 1
                else:
                    changes.append(OpChange(kind=KIND_MOVED, before=a_op, after=b_op, dx=dx, dy=dy))
            else:
                changes.append(OpChange(kind=KIND_RESIZED, before=a_op, after=b_op, dx=dx, dy=dy))

    for i, op in enumerate(parts.a_only):
        if i not in matched_a:
            changes.append(OpChange(kind=KIND_REMOVED, before=op, after=None))
    for j, op in enumerate(parts.b_only):
        if j not in matched_b:
            changes.append(OpChange(kind=KIND_ADDED, before=None, after=op))

    return changes, unchanged_count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _match_pool(
    parts: Partition,
    a_indices: list[int],
    b_indices: list[int],
    gate_radius: float,
    matched_a: set[int],
    matched_b: set[int],
) -> list[tuple[ExpandedOp, ExpandedOp]]:
    """Greedy global matching by centroid distance within *gate_radius*."""
    pairs_out: list[tuple[ExpandedOp, ExpandedOp]] = []
    a_pts = [(parts.a_only[i].centroid_x, parts.a_only[i].centroid_y) for i in a_indices]
    b_pts = [(parts.b_only[j].centroid_x, parts.b_only[j].centroid_y) for j in b_indices]
    tree = cKDTree(b_pts)

    k = min(8, len(b_pts))
    candidates: list[tuple[float, int, int]] = []
    for ai_local, pt in enumerate(a_pts):
        d_raw, i_raw = tree.query(pt, k=k, distance_upper_bound=gate_radius)
        # query on a single point returns scalars for k=1, 1-D arrays otherwise.
        d_arr = np.atleast_1d(np.asarray(d_raw, dtype=float))
        i_arr = np.atleast_1d(np.asarray(i_raw, dtype=int))
        for d, j_local in zip(d_arr, i_arr, strict=True):
            if math.isinf(float(d)) or int(j_local) >= len(b_pts):
                continue
            candidates.append((float(d), ai_local, int(j_local)))

    # Sort by distance (deterministic index tie-break), accept greedily.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    used_a_local: set[int] = set()
    used_b_local: set[int] = set()
    for _d, ai_local, bj_local in candidates:
        if ai_local in used_a_local or bj_local in used_b_local:
            continue
        used_a_local.add(ai_local)
        used_b_local.add(bj_local)
        ai = a_indices[ai_local]
        bj = b_indices[bj_local]
        matched_a.add(ai)
        matched_b.add(bj)
        pairs_out.append((parts.a_only[ai], parts.b_only[bj]))
    return pairs_out


def _dims_same(a: ExpandedOp, b: ExpandedOp, area_tol: float) -> bool:
    """Same dimensions modulo orientation (a rotated pad is still 'moved')."""
    if a.dims_signature != b.dims_signature:
        return False
    biggest = max(a.area, b.area)
    if biggest <= 0.0:
        return True
    return abs(a.area - b.area) / biggest <= area_tol
