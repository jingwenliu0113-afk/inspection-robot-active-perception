"""Confirm-present rule (decision 036 §4), engineering only: OFF by default, not evaluated.

present  <=  some view has an in-zone detection >= ``tau_hi``,
         or  two different views each have an in-zone detection >= ``tau`` whose depth-located
             positions are within ``r`` of each other.

Only the present branch differs from decision-v4: absent and its blocking are unchanged, so a
stricter present can only turn ``present`` into ``inconclusive``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

ViewDets = Sequence[tuple[float, float, float]]  # (confidence, x, y) of in-zone detections


@dataclass(frozen=True)
class ConfirmParams:
    tau: float = 0.7
    tau_hi: float = 0.98
    r: float = 0.25


def confirm_present(views: Sequence[ViewDets], p: ConfirmParams) -> tuple[bool, float]:
    """(present?, confidence). Confidence: the single-view one, or the weaker of the pair."""
    best_single = max((c for v in views for c, _, _ in v), default=0.0)
    if best_single >= p.tau_hi:
        return True, best_single
    best_pair = 0.0
    for i, vi in enumerate(views):
        for vj in views[i + 1 :]:
            for ci, xi, yi in vi:
                if ci < p.tau:
                    continue
                for cj, xj, yj in vj:
                    if cj >= p.tau and math.hypot(xi - xj, yi - yj) <= p.r:
                        best_pair = max(best_pair, min(ci, cj))
    return (best_pair > 0.0), best_pair
