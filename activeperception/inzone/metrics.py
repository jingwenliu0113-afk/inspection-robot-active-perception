"""Metrics for decision 036 (pure functions, unit-tested).

- ``bands``: counts of per-image (or per-view) max confidence in fixed bands.
- ``h2_ceiling``: of the false positives (>= tau), the share at or above ``tau_hi``. The
  confirm-present rule accepts those from a single view, so it can remove at most
  1 - that share of them, however view-dependent the errors are.
- ``recall_exposure``: of the true detections (>= tau), the share in [tau, tau_hi): these
  would need a second, confirming view.
- ``pair_consistency``: P(view j >= tau | view i >= tau) over ordered pairs of views of the same
  object whose azimuths differ by at least ``min_sep``.
- ``exposure``: P(any of k views >= tau) for a per-view rate p, independent vs fully correlated.
- ``cluster_bootstrap_ratio``: percentile CI of a ratio of sums, resampling clusters (objects).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

BAND_EDGES = (0.7, 0.9, 0.95, 0.98, 0.99, 1.0000001)


def bands(conf: Sequence[float], edges: Sequence[float] = BAND_EDGES) -> dict[str, int]:
    c = np.asarray(conf, float)
    out = {f"<{edges[0]}": int((c < edges[0]).sum())}
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        label = f"[{lo}, {min(hi, 1.0)}]" if hi > 1 else f"[{lo}, {hi})"
        out[label] = int(((c >= lo) & (c < hi)).sum())
    return out


def h2_ceiling(conf: Sequence[float], tau: float, tau_hi: float) -> dict:
    c = np.asarray(conf, float)
    fp = int((c >= tau).sum())
    hi = int((c >= tau_hi).sum())
    return {
        "fp": fp,
        "fp_at_or_above_tau_hi": hi,
        "share_unremovable": hi / fp if fp else None,
        "max_relative_reduction": 1 - hi / fp if fp else None,
    }


def recall_exposure(conf: Sequence[float], tau: float, tau_hi: float) -> dict:
    c = np.asarray(conf, float)
    tp = int((c >= tau).sum())
    mid = int(((c >= tau) & (c < tau_hi)).sum())
    return {"detected": tp, "needs_confirmation": mid, "share": mid / tp if tp else None}


def angular_sep(a: float, b: float) -> float:
    d = (a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def pair_counts(
    conf: Sequence[float], azimuth: Sequence[float], tau: float, min_sep: float
) -> tuple[int, int]:
    """(ordered pairs with view i >= tau, of those also view j >= tau) for one object."""
    n_i = n_ij = 0
    for i, (ci, ai) in enumerate(zip(conf, azimuth, strict=True)):
        if ci < tau:
            continue
        for j, (cj, aj) in enumerate(zip(conf, azimuth, strict=True)):
            if i != j and angular_sep(ai, aj) >= min_sep - 1e-9:
                n_i += 1
                n_ij += cj >= tau
    return n_i, n_ij


def pair_consistency(objects: Sequence[tuple[Sequence[float], Sequence[float]]], tau, min_sep):
    """Pooled P(j >= tau | i >= tau) over objects, with per-object counts for a bootstrap."""
    per = [pair_counts(c, a, tau, min_sep) for c, a in objects]
    den = sum(p[0] for p in per)
    num = sum(p[1] for p in per)
    return {"pairs_i": den, "pairs_ij": num, "p": num / den if den else None, "per_object": per}


def exposure(p: float, k: int) -> dict:
    return {"independent": 1 - (1 - p) ** k, "fully_correlated": p}


def cluster_bootstrap_ratio(
    nums: Sequence[float], dens: Sequence[float], n_boot: int = 2000, seed: int = 0
) -> list[float] | None:
    nums, dens = np.asarray(nums, float), np.asarray(dens, float)
    if len(nums) < 2 or dens.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(nums), len(nums))
        d = dens[idx].sum()
        if d > 0:
            vals.append(nums[idx].sum() / d)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def spread(points: Sequence[tuple[float, float]]) -> list[float]:
    """All pairwise distances between located positions of one object."""
    p = np.asarray(points, float).reshape(-1, 2)
    return [float(np.hypot(*(p[i] - p[j]))) for i in range(len(p)) for j in range(i + 1, len(p))]


def summarize_distances(d: Sequence[float], radii=(0.15, 0.25, 0.35)) -> dict:
    a = np.asarray(d, float)
    if not len(a):
        return {"n": 0}
    return {
        "n": int(len(a)),
        "median": float(np.median(a)),
        "p95": float(np.quantile(a, 0.95)),
        "max": float(a.max()),
        **{f"share_le_{r}": float((a <= r).mean()) for r in radii},
    }
