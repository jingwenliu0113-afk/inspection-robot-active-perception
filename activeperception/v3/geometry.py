"""v3 geometry (decision 024, development): see-through-v3, nav-pose-v3, nav-margin-v3.

Deployable only: onboard depth, the pose estimate, the facility map outlines, the zone and a
spec-sheet prior on depth error. The frozen v2 / decision 016 functions are not modified.

- ``location_visibility_v3``: an axis point is seen through when enough pixels of a small
  neighbourhood are valid and *every* valid one lies behind the point (minus the tolerance).
  A missing pixel is neither "seen" nor "blocked" by itself, unlike v2 where one missing pixel
  blocks the location.
- ``refine_pose_v3``: v2's coarse-to-fine 2D alignment with per-point weights from a depth-error
  prior that grows with range, a range cut, a depth-scale search (a scale error moves every
  point along its ray) and a split-half check: the left and right halves of the image are
  aligned separately and their disagreement is the uncertainty used for the margin.
- ``robust_visibility_v3``: per-location minimum of ``location_visibility_v3`` over v2's 27-pose
  set, with the pose spread taken from the uncertainty.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from dataclasses import dataclass

import numpy as np

from ..geometry import project_points
from ..nav.localize import (
    _STAGES,
    INLIER_M,
    MARGIN_FALLBACK,
    MAX_POINTS,
    MIN_EIGENVALUE,
    SEARCH_XY_M,
    SEARCH_YAW,
    TRUNCATE_M,
    Z_BAND_M,
    ZONE_EXCLUDE_M,
    _transform,
    depth_points,
    outline_distance,
    outline_normals,
    pose_set,
)
from ..sensing import LOCATION_TOLERANCE_M, ZONE_LEVELS, location_axis_points, location_grid
from ..types import CameraModel, InspectionZone, Pose

SEE_HALF_PX = 2  # 5 x 5 neighbourhood
SEE_MIN_VALID = 0.4  # fraction of the neighbourhood that must be valid
SPEC_REL_AT_2M = 0.02  # depth error prior: spec-sheet bound (< 2 % within 4 m), grows ~ z^2
SIGMA_FIT_M = 0.02
MAX_RANGE_M = 5.0
SCALES_COARSE = (0.98, 1.0, 1.02)
SCALE_FINE_STEP = 0.005


@dataclass(frozen=True)
class GeometryConfig:
    """Which v3 components are on (ablations); all off = decision 016 geometry."""

    see_v3: bool = True
    weights: bool = True
    scale: bool = True
    max_range: float = MAX_RANGE_M
    min_eigenvalue: float = MIN_EIGENVALUE
    margin_ok: tuple[float, float] = (0.015, 0.005)  # 27-pose spread when the fit passed
    margin_fallback: tuple[float, float] = MARGIN_FALLBACK  # ... when it failed
    split_half: bool = False  # dev finding: half-image fits disagree for geometric reasons,
    margin_k: float = 0.0  # not because of the error (corr 0.04-0.22) -> off
    prior_k: float = 0.0  # > 0: reject a fit that moves the estimate > k sigma (localiser's own
    #                       covariance) - a wrong convergence; and fall back with >= k sigma margin
    name: str = "v3"


V2_GEOMETRY = GeometryConfig(see_v3=False, weights=False, scale=False, max_range=6.0, name="v2")


# ---------------------------------------------------------------- see-through


def location_visibility_v3(
    depth: np.ndarray,
    camera: CameraModel,
    pose: Pose,
    zone: InspectionZone,
    half: int = SEE_HALF_PX,
    min_valid: float = SEE_MIN_VALID,
    tolerance: float = LOCATION_TOLERANCE_M,
) -> tuple[float, ...]:
    grid = location_grid(zone)
    pts = location_axis_points(zone, grid)
    uv, planar, in_fov = project_points(camera, pose, pts)
    seen = np.zeros(len(pts), dtype=bool)
    idx = np.flatnonzero(in_fov)
    if len(idx):
        offs = np.arange(-half, half + 1)
        u0 = np.floor(uv[idx, 0]).astype(int)
        v0 = np.floor(uv[idx, 1]).astype(int)
        uu = np.clip(u0[:, None, None] + offs[None, None, :], 0, camera.width - 1)
        vv = np.clip(v0[:, None, None] + offs[None, :, None], 0, camera.height - 1)
        patch = depth[vv, uu].astype(float)
        valid = ~np.isnan(patch)  # +inf (no return within range) is a valid "far" reading
        behind = np.where(valid, patch >= planar[idx, None, None] - tolerance, True)
        enough = valid.sum(axis=(1, 2)) >= min_valid * patch[0].size
        seen[idx] = enough & behind.all(axis=(1, 2))
    per_loc = seen.reshape(len(grid), len(ZONE_LEVELS)).mean(axis=1)
    return tuple(float(v) for v in per_loc)


# ---------------------------------------------------------------- pose refinement


@dataclass(frozen=True)
class RefinementV3:
    pose: Pose
    ok: bool
    dx: float
    dy: float
    dyaw: float
    scale: float
    n_points: int
    min_eigenvalue: float
    spread_xy: float  # split-half disagreement (0 if not computed)
    spread_yaw: float


def _points(depth, camera, pose, zone, max_range) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(points 2D, horizontal range, image column) of obstacle pixels."""
    p3 = depth_points(depth, camera, pose)
    from ..nav.localize import STRIDE

    v, u = np.mgrid[0 : camera.height : STRIDE, 0 : camera.width : STRIDE]
    d = depth[v, u].astype(float)
    ok = np.isfinite(d) & (d > 0) & (d <= 6.0)
    cols = u[ok]
    c = np.array([pose.x, pose.y])
    rng = np.hypot(p3[:, 0] - c[0], p3[:, 1] - c[1])
    keep = (p3[:, 2] >= Z_BAND_M[0]) & (p3[:, 2] <= Z_BAND_M[1])
    keep &= np.hypot(p3[:, 0] - zone.cx, p3[:, 1] - zone.cy) > ZONE_EXCLUDE_M
    keep &= rng <= max_range
    return p3[keep, :2], rng[keep], cols[keep]


def _weights(rng: np.ndarray, on: bool) -> np.ndarray:
    if not on:
        return np.ones_like(rng)
    sz = SPEC_REL_AT_2M * 2.0 * (rng / 2.0) ** 2
    w = 1.0 / (SIGMA_FIT_M**2 + sz**2)
    return w / w.mean()


def _wcost(dist: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.sum(w * np.minimum(dist, TRUNCATE_M) ** 2, axis=-1) / np.sum(w)


def _align(pts, w, c, outlines, scales_coarse, fine_scale: bool):
    """Coarse-to-fine search over (dx, dy, dyaw[, scale]); scale applied about the camera."""
    best = (0.0, 0.0, 0.0, 1.0)
    for k, (hxy, sxy, hyaw, syaw) in enumerate(_STAGES):
        offs = np.arange(-hxy, hxy + 1e-9, sxy)
        yaws = np.arange(-hyaw, hyaw + 1e-9, syaw)
        txy = np.array(list(itertools.product(offs, offs)))
        if k == 0:
            scales = (1.0,)
        elif k == 1:
            scales = scales_coarse
        else:
            s0 = best[3]
            scales = (s0 - SCALE_FINE_STEP, s0, s0 + SCALE_FINE_STEP) if fine_scale else (s0,)
        top = (np.inf, best)
        for s in scales:
            scaled = c + (pts - c) / s
            for dyaw in yaws:
                rot = _transform(scaled, c, 0.0, 0.0, best[2] + dyaw)
                px = rot[None, :, 0] + best[0] + txy[:, :1]
                py = rot[None, :, 1] + best[1] + txy[:, 1:]
                cost = _wcost(outline_distance(px, py, outlines), w)
                j = int(np.argmin(cost))
                if cost[j] < top[0]:
                    top = (
                        float(cost[j]),
                        (best[0] + txy[j, 0], best[1] + txy[j, 1], best[2] + dyaw, s),
                    )
        best = top[1]
    return best


def _subsample(n: int, k: int, seed: int) -> np.ndarray:
    if n <= k:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, k, replace=False))


def refine_pose_v3(
    depth: np.ndarray,
    camera: CameraModel,
    estimate: Pose,
    zone: InspectionZone,
    outlines,
    cfg: GeometryConfig,
    min_points: int = 50,
    prior: tuple[float, float] | None = None,
) -> RefinementV3:
    """``prior`` = (sigma_xy per axis, sigma_yaw) the localiser reports for ``estimate``."""
    pts, rng, cols = _points(depth, camera, estimate, zone, cfg.max_range)
    c = np.array([estimate.x, estimate.y])
    fail = RefinementV3(estimate, False, 0.0, 0.0, 0.0, 1.0, len(pts), 0.0, math.inf, math.inf)
    if len(pts) < min_points:
        return fail
    sel = _subsample(len(pts), MAX_POINTS, 0)
    w = _weights(rng, cfg.weights)
    scales = SCALES_COARSE if cfg.scale else (1.0,)
    dx, dy, dyaw, s = _align(pts[sel], w[sel], c, outlines, scales, cfg.scale)
    moved = _transform(c + (pts - c) / s, c, dx, dy, dyaw)
    dist = outline_distance(moved[:, 0], moved[:, 1], outlines)
    inl = dist < INLIER_M
    eig = 0.0
    if inl.sum() >= 3:
        n = outline_normals(moved[inl], outlines)
        lever = moved[inl] - (c + (dx, dy))
        j = np.column_stack([n[:, 0], n[:, 1], n[:, 0] * -lever[:, 1] + n[:, 1] * lever[:, 0]])
        eig = float(np.linalg.eigvalsh(j.T @ j)[0])
    in_window = abs(dx) < SEARCH_XY_M - 1e-6 and abs(dy) < SEARCH_XY_M - 1e-6
    in_window &= abs(dyaw) < SEARCH_YAW - 1e-6
    ok = bool(eig >= cfg.min_eigenvalue and in_window)
    if ok and cfg.prior_k > 0 and prior is not None:
        sxy, syaw = prior
        ok = abs(dx) <= cfg.prior_k * sxy and abs(dy) <= cfg.prior_k * sxy
        ok = bool(ok and abs(dyaw) <= cfg.prior_k * syaw)
    spread_xy = spread_yaw = 0.0
    if ok and cfg.split_half:
        mid = camera.width / 2
        halves = []
        for side in (cols < mid, cols >= mid):
            idx = np.flatnonzero(side)
            if len(idx) < min_points:
                halves = None
                break
            idx = idx[_subsample(len(idx), MAX_POINTS // 2, 1)]
            halves.append(_align(pts[idx], w[idx], c, outlines, (s,), False))
        if halves is None:
            spread_xy, spread_yaw = math.inf, math.inf
        else:
            (ax, ay, ayaw, _), (bx, by, byaw, _) = halves
            spread_xy = math.hypot(ax - bx, ay - by)
            spread_yaw = abs(ayaw - byaw)
    pose = dataclasses.replace(
        estimate, x=estimate.x + dx, y=estimate.y + dy, yaw=estimate.yaw + dyaw
    )
    return RefinementV3(
        pose if ok else estimate, ok, float(dx), float(dy), float(dyaw), float(s), len(pts), eig,
        spread_xy, spread_yaw,
    )  # fmt: skip


def margin_for(
    ref: RefinementV3, cfg: GeometryConfig, prior: tuple[float, float] | None = None
) -> tuple[float, float]:
    """Pose spread of the 27-pose set: fallback when the fit failed (at least k sigma of the
    localiser's covariance when ``prior_k`` is on), else the configured margin (widened to
    k * split-half disagreement only when that check is on)."""
    if not ref.ok or not math.isfinite(ref.spread_xy):
        fx, fyaw = cfg.margin_fallback
        if cfg.prior_k > 0 and prior is not None:
            return max(fx, cfg.prior_k * prior[0]), max(fyaw, cfg.prior_k * prior[1])
        return fx, fyaw
    fx, fyaw = cfg.margin_ok
    return max(fx, cfg.margin_k * ref.spread_xy), max(fyaw, cfg.margin_k * ref.spread_yaw)


def robust_visibility_v3(depth, camera, pose, zone, dxy, dyaw, see_v3: bool) -> tuple[float, ...]:
    from ..sensing import location_visibility_from_depth

    fn = location_visibility_v3 if see_v3 else location_visibility_from_depth
    vis = np.array([fn(depth, camera, p, zone) for p in pose_set(pose, dxy, dyaw)])
    return tuple(float(v) for v in vis.min(axis=0))
