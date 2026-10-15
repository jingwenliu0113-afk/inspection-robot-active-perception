"""nav-pose-v4 (decision 029, development): v3's refinement with a search window that covers the
localiser's prior, a uniqueness check and a configurable depth-scale search.

The v3 failure (decision 026, V4): the 2D alignment only searched +-15 cm around the estimate. With
L2 (sigma 6 cm) the localiser-prior gate (3 sigma = 18 cm) is wider than that window, so it never
fired; an estimate 21.5 cm off had its true pose outside the window and the fit settled on a wrong
minimum inside it, believing itself.

- ``window_k``: half-width of the coarse search = max(v3's window, k * the localiser's sigma). With
  k > ``prior_k`` the true pose stays inside the window for estimates beyond the gate, so a correct
  fit to a far-off estimate moves > ``prior_k`` sigma and becomes a conflict (the view clears
  nothing) instead of a wrong convergence that looks fine.
- ``unique_ratio`` / ``unique_m``: on the coarse grid (scale 1), the best cost at least ``unique_m``
  away from the solution must exceed the best cost near it by this factor; otherwise the fit is
  ambiguous and is treated as a conflict.
- ``scales``: the coarse depth-scale candidates (v3: 0.98 / 1.0 / 1.02), each refined by +-0.005.

With the defaults this is exactly ``v3.geometry.refine_pose_v3`` (tested).
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from dataclasses import dataclass

import numpy as np

from ..nav.localize import (
    _STAGES,
    INLIER_M,
    MAX_POINTS,
    SEARCH_XY_M,
    SEARCH_YAW,
    _transform,
    outline_distance,
    outline_normals,
)
from ..v3 import geometry as g3
from ..v3.geometry import GeometryConfig, RefinementV3

COARSE_STEP_XY = _STAGES[0][1]  # 3 cm
COARSE_STEP_YAW = _STAGES[0][3]  # 0.01 rad


@dataclass(frozen=True)
class GeometryConfigV4(GeometryConfig):
    window_k: float = 0.0  # 0 = v3's fixed window
    unique_ratio: float = 0.0  # 0 = off
    unique_m: float = 0.09
    scales: tuple[float, ...] = g3.SCALES_COARSE
    # scale hypotheses: a full search per fixed depth scale; the poses of the near-optimal ones
    # (cost <= hyp_ratio x best) spread along the scale-translation coupling. () = off (v3).
    hyp_scales: tuple[float, ...] = ()
    hyp_ratio: float = 1.10
    hyp_points: int = 500  # coarse stage of each hypothesis on a subset
    hyp_blind_m: float = math.inf  # spread beyond this -> the pose is not trusted (conflict)
    hyp_margin: bool = True  # margin = margin_ok + spread
    name: str = "v4-dev"


@dataclass(frozen=True)
class RefinementV4(RefinementV3):
    window_xy: float = SEARCH_XY_M
    window_yaw: float = SEARCH_YAW
    unique: float = math.inf  # coarse grid: best cost >= unique_m away / best cost near the fit
    ambiguous: bool = False


def _windows(cfg: GeometryConfigV4, prior) -> tuple[float, float]:
    if cfg.window_k <= 0 or prior is None:
        return SEARCH_XY_M, SEARCH_YAW
    return max(SEARCH_XY_M, cfg.window_k * prior[0]), max(SEARCH_YAW, cfg.window_k * prior[1])


def _align(pts, w, c, outlines, scales, fine_scale: bool, hxy0: float, hyaw0: float, unique_m):
    """v3's coarse-to-fine search with a configurable coarse window. Also returns the coarse
    cost grid (scale 1, every yaw) to judge how unique the solution is."""
    best = (0.0, 0.0, 0.0, 1.0)
    coarse = None
    stages = ((hxy0, _STAGES[0][1], hyaw0, _STAGES[0][3]), *_STAGES[1:])
    for k, (hxy, sxy, hyaw, syaw) in enumerate(stages):
        offs = np.arange(-hxy, hxy + 1e-9, sxy)
        yaws = np.arange(-hyaw, hyaw + 1e-9, syaw)
        txy = np.array(list(itertools.product(offs, offs)))
        if k == 0:
            scale_set = (1.0,)
        elif k == 1:
            scale_set = scales
        else:
            s0 = best[3]
            step = g3.SCALE_FINE_STEP
            scale_set = (s0 - step, s0, s0 + step) if fine_scale else (s0,)
        top = (np.inf, best)
        grid = [] if k == 0 else None
        for s in scale_set:
            scaled = c + (pts - c) / s
            for dyaw in yaws:
                rot = _transform(scaled, c, 0.0, 0.0, best[2] + dyaw)
                px = rot[None, :, 0] + best[0] + txy[:, :1]
                py = rot[None, :, 1] + best[1] + txy[:, 1:]
                cost = g3._wcost(outline_distance(px, py, outlines), w)
                if grid is not None:
                    grid.append(cost)
                j = int(np.argmin(cost))
                if cost[j] < top[0]:
                    top = (
                        float(cost[j]),
                        (best[0] + txy[j, 0], best[1] + txy[j, 1], best[2] + dyaw, s),
                    )
        if grid is not None:
            coarse = (txy, np.array(grid))
        best = top[1]
    if unique_m is None:
        return best, math.inf
    txy, grid = coarse  # scale 1, every coarse yaw: the near / far minima are compared alike
    far = np.hypot(txy[:, 0] - best[0], txy[:, 1] - best[1]) >= unique_m
    if not far.any():
        return best, math.inf
    near = float(grid[:, ~far].min())
    return best, float(grid[:, far].min()) / near if near > 0 else math.inf


def _search(pts, w, c, outlines, s, stages, coarse_pts):
    """Coarse-to-fine (dx, dy, dyaw) at a fixed depth scale; the first stage on a subset."""
    best = (0.0, 0.0, 0.0)
    cost_best = math.inf
    scaled = c + (pts - c) / s
    for k, (hxy, sxy, hyaw, syaw) in enumerate(stages):
        q, ww = (scaled[coarse_pts], w[coarse_pts]) if k == 0 else (scaled, w)
        offs = np.arange(-hxy, hxy + 1e-9, sxy)
        yaws = np.arange(-hyaw, hyaw + 1e-9, syaw)
        txy = np.array(list(itertools.product(offs, offs)))
        top = (np.inf, best)
        for dyaw in yaws:
            rot = _transform(q, c, 0.0, 0.0, best[2] + dyaw)
            px = rot[None, :, 0] + best[0] + txy[:, :1]
            py = rot[None, :, 1] + best[1] + txy[:, 1:]
            cost = g3._wcost(outline_distance(px, py, outlines), ww)
            j = int(np.argmin(cost))
            if cost[j] < top[0]:
                top = (float(cost[j]), (best[0] + txy[j, 0], best[1] + txy[j, 1], best[2] + dyaw))
        cost_best, best = top
    return best, cost_best


def _hypotheses(pts, w, c, outlines, cfg, hxy0, hyaw0):
    """One search per hypothesised scale (stages 0-1), then the fine stage (with v3's +-0.005
    scale refinement) for the best one. Returns the fit and the near-optimal hypotheses."""
    stages01 = ((hxy0, _STAGES[0][1], hyaw0, _STAGES[0][3]), _STAGES[1])
    sub = g3._subsample(len(pts), cfg.hyp_points, 2)
    hyps = []
    for s in cfg.hyp_scales:
        pose, cost = _search(pts, w, c, outlines, s, stages01, sub)
        hyps.append((cost, s, pose))
    cost0, s0, p0 = min(hyps)
    fine = []
    step = g3.SCALE_FINE_STEP
    for s in (s0 - step, s0, s0 + step):
        scaled = c + (pts - c) / s
        best, top = p0, (math.inf, p0)
        hxy, sxy, hyaw, syaw = _STAGES[2]
        offs = np.arange(-hxy, hxy + 1e-9, sxy)
        txy = np.array(list(itertools.product(offs, offs)))
        for dyaw in np.arange(-hyaw, hyaw + 1e-9, syaw):
            rot = _transform(scaled, c, 0.0, 0.0, best[2] + dyaw)
            px = rot[None, :, 0] + best[0] + txy[:, :1]
            py = rot[None, :, 1] + best[1] + txy[:, 1:]
            cost = g3._wcost(outline_distance(px, py, outlines), w)
            j = int(np.argmin(cost))
            if cost[j] < top[0]:
                top = (float(cost[j]), (best[0] + txy[j, 0], best[1] + txy[j, 1], best[2] + dyaw))
        fine.append((top[0], s, top[1]))
    _, s_fit, (dx, dy, dyaw) = min(fine)
    near = [h for h in hyps if h[0] <= cfg.hyp_ratio * cost0]
    spread_xy = max(math.hypot(h[2][0] - dx, h[2][1] - dy) for h in near)
    spread_yaw = max(abs(h[2][2] - dyaw) for h in near)
    return (dx, dy, dyaw, s_fit), spread_xy, spread_yaw


def refine_pose_v4(
    depth: np.ndarray,
    camera,
    estimate,
    zone,
    outlines,
    cfg: GeometryConfigV4,
    min_points: int = 50,
    prior: tuple[float, float] | None = None,
) -> RefinementV4:
    pts, rng, _ = g3._points(depth, camera, estimate, zone, cfg.max_range)
    c = np.array([estimate.x, estimate.y])
    hxy, hyaw = _windows(cfg, prior)
    fail = RefinementV4(
        estimate, False, 0.0, 0.0, 0.0, 1.0, len(pts), 0.0, math.inf, math.inf,
        window_xy=hxy, window_yaw=hyaw,
    )  # fmt: skip
    if len(pts) < min_points:
        return fail
    sel = g3._subsample(len(pts), MAX_POINTS, 0)
    w = g3._weights(rng, cfg.weights)
    scales = cfg.scales if cfg.scale else (1.0,)
    unique_m = cfg.unique_m if cfg.unique_ratio > 0 else None
    spread_xy = spread_yaw = 0.0
    if cfg.hyp_scales:
        (dx, dy, dyaw, s), spread_xy, spread_yaw = _hypotheses(
            pts[sel], w[sel], c, outlines, cfg, hxy, hyaw
        )
        unique = math.inf
    else:
        (dx, dy, dyaw, s), unique = _align(
            pts[sel], w[sel], c, outlines, scales, cfg.scale, hxy, hyaw, unique_m
        )
    moved = _transform(c + (pts - c) / s, c, dx, dy, dyaw)
    dist = outline_distance(moved[:, 0], moved[:, 1], outlines)
    inl = dist < INLIER_M
    eig = 0.0
    if inl.sum() >= 3:
        n = outline_normals(moved[inl], outlines)
        lever = moved[inl] - (c + (dx, dy))
        j = np.column_stack([n[:, 0], n[:, 1], n[:, 0] * -lever[:, 1] + n[:, 1] * lever[:, 0]])
        eig = float(np.linalg.eigvalsh(j.T @ j)[0])
    in_window = abs(dx) < hxy - 1e-6 and abs(dy) < hxy - 1e-6 and abs(dyaw) < hyaw - 1e-6
    conditioned = eig >= cfg.min_eigenvalue
    ok = bool(conditioned and in_window)
    if ok and cfg.prior_k > 0 and prior is not None:
        sxy, syaw = prior
        ok = abs(dx) <= cfg.prior_k * sxy and abs(dy) <= cfg.prior_k * sxy
        ok = bool(ok and abs(dyaw) <= cfg.prior_k * syaw)
    ambiguous = bool(ok and unique_m is not None and unique < cfg.unique_ratio)
    ambiguous |= bool(ok and spread_xy > cfg.hyp_blind_m)
    ok = ok and not ambiguous
    conflict = bool(conditioned and not ok)
    pose = dataclasses.replace(
        estimate, x=estimate.x + dx, y=estimate.y + dy, yaw=estimate.yaw + dyaw
    )
    return RefinementV4(
        pose if ok else estimate, ok, float(dx), float(dy), float(dyaw), float(s), len(pts), eig,
        spread_xy, spread_yaw, conflict, window_xy=hxy, window_yaw=hyaw,
        unique=unique, ambiguous=ambiguous,
    )  # fmt: skip


def margin_for_v4(ref, cfg: GeometryConfigV4, prior=None) -> tuple[float, float]:
    """v3's margins; with scale hypotheses on, a trusted fit adds their pose spread."""
    fx, fyaw = g3.margin_for(ref, dataclasses.replace(cfg, margin_k=0.0), prior)
    if ref.ok and cfg.hyp_scales and cfg.hyp_margin:
        return fx + ref.spread_xy, fyaw + ref.spread_yaw
    return fx, fyaw
