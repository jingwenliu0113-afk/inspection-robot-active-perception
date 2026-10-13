"""Pose refinement against the prior facility map and pose-robust see-through (decision 016).

``nav-pose-v1`` (``refine_pose``): obstacle points of the onboard depth image (0.15-0.85 m
above the ground, away from the inspection zone) are aligned in 2D to the outlines of the
walls and pillars of the vector facility map, starting from the AMCL estimate. Only
deployable inputs: depth, the estimate, the mast extrinsics (in the pose), the map
outlines (never the target) and the zone. Unknown objects become outliers of the truncated
cost.

``nav-margin-v1`` (``robust_location_visibility``): a location counts as seen through only
if it is seen through from every pose of a small set around the pose (+-dxy along the
camera's forward and lateral axes, +-dyaw), i.e. the per-location minimum.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from dataclasses import dataclass

import numpy as np

from ..geometry import rotation_matrix
from ..sensing import location_visibility_from_depth
from ..types import Box, CameraModel, EpisodeSpec, InspectionZone, Pose
from . import scene

POSE_VERSION = "nav-pose-v1"
MARGIN_VERSION = "nav-margin-v1"
STRIDE = 4
MAX_RANGE_M = 6.0
Z_BAND_M = (0.15, 0.85)
ZONE_EXCLUDE_M = 0.6
TRUNCATE_M = 0.10
INLIER_M = 0.03
SEARCH_XY_M = 0.15
SEARCH_YAW = 0.08
MAX_POINTS = 1500
# frozen on nav-b0 (decision 016 appendix A): degeneracy threshold, margins
MIN_EIGENVALUE = 10.0
MARGIN_OK = (0.015, 0.005)  # 2 x p95 refined error on nav-b0 (0.74 cm, 0.0025 rad), floors
MARGIN_FALLBACK = (0.10, 0.06)  # refinement degenerate -> AMCL estimate with a wide margin
_STAGES = (  # (half-width xy, step xy, half-width yaw, step yaw)
    (SEARCH_XY_M, 0.03, SEARCH_YAW, 0.01),
    (0.03, 0.005, 0.012, 0.002),
    (0.006, 0.001, 0.0024, 0.0004),
)


def inner_wall_faces() -> tuple[Box, ...]:
    """The enclosure as its inner faces (zero-thickness boxes). The robot is always inside, so
    only these faces are visible; full-thickness walls let the fit slide points onto the
    outer faces (0.1 m off along each axis, seen in the nav-b0 dev data)."""
    h, span = scene.WALL_HALF_M, 2 * scene.WALL_HALF_M
    return (
        Box(cx=h, cy=0.0, cz=1.0, sx=0.0, sy=span, sz=2.0),
        Box(cx=-h, cy=0.0, cz=1.0, sx=0.0, sy=span, sz=2.0),
        Box(cx=0.0, cy=h, cz=1.0, sx=span, sy=0.0, sz=2.0),
        Box(cx=0.0, cy=-h, cz=1.0, sx=span, sy=0.0, sz=2.0),
    )


def map_outlines(spec: EpisodeSpec) -> tuple[Box, ...]:
    """Vector facility map: inner wall faces and pillar footprints. Never the target or zone."""
    return (*inner_wall_faces(), *spec.layout.occluders)


def depth_points(depth: np.ndarray, camera: CameraModel, pose: Pose) -> np.ndarray:
    """World points (N, 3) of every ``STRIDE``-th pixel with a valid planar depth."""
    f = camera.focal_px
    v, u = np.mgrid[0 : camera.height : STRIDE, 0 : camera.width : STRIDE]
    d = depth[v, u].astype(float)
    ok = np.isfinite(d) & (d > 0) & (d <= MAX_RANGE_M)
    d, u, v = d[ok], u[ok] + 0.5, v[ok] + 0.5
    cam = np.stack([d, -(u - camera.width / 2) / f * d, -(v - camera.height / 2) / f * d], axis=1)
    return cam @ rotation_matrix(pose.yaw, pose.pitch).T + np.array(pose.position())


def obstacle_points_2d(points: np.ndarray, zone: InspectionZone) -> np.ndarray:
    z = points[:, 2]
    keep = (z >= Z_BAND_M[0]) & (z <= Z_BAND_M[1])
    keep &= np.hypot(points[:, 0] - zone.cx, points[:, 1] - zone.cy) > ZONE_EXCLUDE_M
    return points[keep, :2]


def outline_distance(px: np.ndarray, py: np.ndarray, boxes) -> np.ndarray:
    """Distance of each point to the nearest box outline (inside or outside the box)."""
    best = np.full(np.broadcast(px, py).shape, np.inf)
    for b in boxes:
        dx = np.abs(px - b.cx) - b.sx / 2
        dy = np.abs(py - b.cy) - b.sy / 2
        outside = np.hypot(np.maximum(dx, 0.0), np.maximum(dy, 0.0))
        inside = np.minimum(np.maximum(dx, dy), 0.0)
        best = np.minimum(best, np.abs(outside + inside))
    return best


def outline_normals(p: np.ndarray, boxes) -> np.ndarray:
    """Unit normal of the nearest outline at each point (numerical gradient)."""
    h = 1e-4
    gx = outline_distance(p[:, 0] + h, p[:, 1], boxes) - outline_distance(
        p[:, 0] - h, p[:, 1], boxes
    )
    gy = outline_distance(p[:, 0], p[:, 1] + h, boxes) - outline_distance(
        p[:, 0], p[:, 1] - h, boxes
    )
    g = np.stack([gx, gy], axis=1)
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)


@dataclass(frozen=True)
class Refinement:
    pose: Pose  # refined camera pose (the estimate itself when not ``ok``)
    ok: bool
    dx: float
    dy: float
    dyaw: float
    n_points: int
    inlier_fraction: float
    min_eigenvalue: float  # weakest direction of the inlier constraint matrix (x, y, yaw * 1 m)
    cost: float


def _transform(p: np.ndarray, c: np.ndarray, dx: float, dy: float, dyaw: float) -> np.ndarray:
    cs, sn = math.cos(dyaw), math.sin(dyaw)
    q = p - c
    return (
        np.stack([cs * q[:, 0] - sn * q[:, 1], sn * q[:, 0] + cs * q[:, 1]], axis=1) + c + (dx, dy)
    )


def _cost(dist: np.ndarray) -> np.ndarray:
    return np.mean(np.minimum(dist, TRUNCATE_M) ** 2, axis=-1)


def refine_pose(
    depth: np.ndarray,
    camera: CameraModel,
    estimate: Pose,
    zone: InspectionZone,
    outlines,
    min_eigenvalue: float = MIN_EIGENVALUE,
    min_points: int = 50,
) -> Refinement:
    """Align depth obstacle points to the map outlines around ``estimate`` (no ground truth)."""
    pts = obstacle_points_2d(depth_points(depth, camera, estimate), zone)
    c = np.array([estimate.x, estimate.y])
    if len(pts) < min_points:
        return Refinement(estimate, False, 0.0, 0.0, 0.0, len(pts), 0.0, 0.0, float("nan"))
    rng = np.random.default_rng(0)
    sub = pts if len(pts) <= MAX_POINTS else pts[rng.choice(len(pts), MAX_POINTS, replace=False)]
    best = (0.0, 0.0, 0.0)
    for hxy, sxy, hyaw, syaw in _STAGES:
        offs = np.arange(-hxy, hxy + 1e-9, sxy)
        yaws = np.arange(-hyaw, hyaw + 1e-9, syaw)
        txy = np.array(list(itertools.product(offs, offs)))
        top = (np.inf, best)
        for dyaw in yaws:
            rot = _transform(sub, c, 0.0, 0.0, best[2] + dyaw)
            px = rot[None, :, 0] + best[0] + txy[:, :1]
            py = rot[None, :, 1] + best[1] + txy[:, 1:]
            cost = _cost(outline_distance(px, py, outlines))
            k = int(np.argmin(cost))
            if cost[k] < top[0]:
                top = (float(cost[k]), (best[0] + txy[k, 0], best[1] + txy[k, 1], best[2] + dyaw))
        best = top[1]
    dx, dy, dyaw = best
    moved = _transform(pts, c, dx, dy, dyaw)
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
    ok = bool(eig >= min_eigenvalue and in_window)
    pose = dataclasses.replace(
        estimate, x=estimate.x + dx, y=estimate.y + dy, yaw=estimate.yaw + dyaw
    )
    return Refinement(
        pose if ok else estimate,
        ok,
        float(dx),
        float(dy),
        float(dyaw),
        len(pts),
        float(inl.mean()),
        eig,
        float(_cost(dist)),
    )


def pose_set(pose: Pose, dxy: float, dyaw: float) -> list[Pose]:
    """27 poses: {-dxy, 0, +dxy} along forward and lateral x {-dyaw, 0, +dyaw}."""
    fx, fy = math.cos(pose.yaw), math.sin(pose.yaw)
    out = []
    for a, b, w in itertools.product((-1, 0, 1), repeat=3):
        out.append(
            dataclasses.replace(
                pose,
                x=pose.x + a * dxy * fx - b * dxy * fy,
                y=pose.y + a * dxy * fy + b * dxy * fx,
                yaw=pose.yaw + w * dyaw,
            )
        )
    return out


def robust_location_visibility(
    depth: np.ndarray,
    camera: CameraModel,
    pose: Pose,
    zone: InspectionZone,
    dxy: float,
    dyaw: float,
) -> tuple[float, ...]:
    """Per-location minimum of ``location_visibility_from_depth`` over ``pose_set``."""
    vis = np.array(
        [location_visibility_from_depth(depth, camera, p, zone) for p in pose_set(pose, dxy, dyaw)]
    )
    return tuple(float(v) for v in vis.min(axis=0))


def deployable_pose_and_visibility(
    depth: np.ndarray, camera: CameraModel, estimate: Pose, zone: InspectionZone, outlines
) -> tuple[Pose, tuple[float, ...], Refinement]:
    """decision 016 pipeline: refine the estimate, then pose-robust see-through."""
    ref = refine_pose(depth, camera, estimate, zone, outlines)
    dxy, dyaw = MARGIN_OK if ref.ok else MARGIN_FALLBACK
    return ref.pose, robust_location_visibility(depth, camera, ref.pose, zone, dxy, dyaw), ref
