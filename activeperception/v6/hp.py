"""H-P (decision 037 §3 / appendix A): is a fit-localiser conflict supported by the depth?

The ratio compares the refinement's own alignment cost at the localiser's pose (best of the
hypothesised depth scales, no shift) with its cost at the fit. Near 1, the depth cannot tell the
two apart (dev, D3xP0: p50 1.18); a localiser that is really off explains the depth far worse
(dev, D1xL2 reporting L1, localiser wrong: p50 32.8). Uses only the depth, the map and the
localiser's pose - nothing a robot does not have.
"""

from __future__ import annotations

import numpy as np

MIN_POINTS = 50  # as the refinement


def fit_costs(depth, camera, est, zone, outlines, cfg, ref) -> dict | None:
    """Alignment cost at the fit and at the localiser's pose (best hypothesised scale), on the
    refinement's points, subsample, weights and scale Jacobian."""
    from ..nav.localize import MAX_POINTS, _transform, outline_distance
    from ..v3 import geometry as g3

    pts, rng, _ = g3._points(depth, camera, est, zone, cfg.max_range)
    if len(pts) < MIN_POINTS:
        return None
    c = np.array([est.x, est.y])
    sel = g3._subsample(len(pts), MAX_POINTS, 0)
    p, w = pts[sel], g3._weights(rng, cfg.weights)[sel]

    def cost(dx, dy, dyaw, s):
        jac = s if cfg.scale_jacobian else 1.0
        moved = _transform(c + (p - c) / s, c, dx, dy, dyaw)
        return float(g3._wcost(jac * outline_distance(moved[:, 0], moved[:, 1], outlines), w))

    best = cost(ref.dx, ref.dy, ref.dyaw, ref.scale)
    at_est = min(cost(0.0, 0.0, 0.0, s) for s in cfg.hyp_scales)
    return {"cost_fit": best, "cost_at_localiser": at_est, "ratio": at_est / best if best else None}


def cost_ratio(depth, camera, est, zone, outlines, cfg, ref) -> float | None:
    """C(localiser) / C(fit); None when it cannot be computed (then the view stays blind)."""
    c = fit_costs(depth, camera, est, zone, outlines, cfg, ref)
    return None if c is None else c["ratio"]


def trusts_localiser(ratio: float | None, c: float) -> bool:
    return ratio is not None and bool(np.isfinite(ratio)) and ratio <= c
