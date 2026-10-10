"""Pinhole projection and segment-vs-box occlusion tests (numpy, vectorised)."""

from __future__ import annotations

import math

import numpy as np

from .types import Box, CameraModel, Pose


def rotation_matrix(yaw: float, pitch: float) -> np.ndarray:
    """World-from-camera rotation: Rz(yaw) @ Ry(pitch). Camera x forward, y left, z up."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    return rz @ ry


def forward_vector(pose: Pose) -> np.ndarray:
    return rotation_matrix(pose.yaw, pose.pitch) @ np.array([1.0, 0.0, 0.0])


def look_at_pose(position: np.ndarray, target: np.ndarray) -> Pose:
    dx, dy, dz = (float(v) for v in (target - position))
    yaw = math.atan2(dy, dx)
    pitch = math.atan2(-dz, math.hypot(dx, dy))
    return Pose(float(position[0]), float(position[1]), float(position[2]), yaw, pitch)


def project_points(
    camera: CameraModel, pose: Pose, points: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project world points (N,3) -> pixel coords (N,2), depth (N,), in_fov (N,) bool."""
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    rot = rotation_matrix(pose.yaw, pose.pitch)
    cam = (pts - np.array(pose.position())) @ rot  # == rot.T @ (p - c) for each row
    depth = cam[:, 0]
    f = camera.focal_px
    with np.errstate(divide="ignore", invalid="ignore"):
        u = f * (-cam[:, 1]) / depth + camera.width / 2.0
        v = f * (-cam[:, 2]) / depth + camera.height / 2.0
    in_fov = (depth > 1e-6) & (u >= 0) & (u < camera.width) & (v >= 0) & (v < camera.height)
    uv = np.stack([u, v], axis=1)
    return uv, depth, in_fov


def box_bounds(box: Box) -> tuple[np.ndarray, np.ndarray]:
    c = np.array([box.cx, box.cy, box.cz])
    h = np.array([box.sx, box.sy, box.sz]) / 2.0
    return c - h, c + h


def segments_blocked(origin: np.ndarray, targets: np.ndarray, boxes: list[Box] | tuple[Box, ...]):
    """For each segment origin->target, True if it intersects any box (slab test)."""
    o = np.asarray(origin, dtype=float).reshape(1, 3)
    t = np.asarray(targets, dtype=float).reshape(-1, 3)
    d = t - o
    blocked = np.zeros(len(t), dtype=bool)
    for box in boxes:
        lo, hi = box_bounds(box)
        zero = d == 0.0
        inside = (o >= lo) & (o <= hi)
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = (lo - o) / d
            t2 = (hi - o) / d
        t_near = np.minimum(t1, t2)
        t_far = np.maximum(t1, t2)
        # axis-parallel segments: inside the slab -> no constraint, outside -> can never hit
        t_near = np.where(zero, np.where(inside, -np.inf, np.inf), t_near)
        t_far = np.where(zero, np.where(inside, np.inf, -np.inf), t_far)
        tmin = t_near.max(axis=1)
        tmax = t_far.min(axis=1)
        hit = (tmax >= tmin) & (tmax >= 0.0) & (tmin <= 1.0)
        blocked |= hit
    return blocked


def fibonacci_sphere(n: int) -> np.ndarray:
    """Deterministic quasi-uniform unit sphere samples (N,3)."""
    i = np.arange(n, dtype=float) + 0.5
    phi = math.pi * (3.0 - math.sqrt(5.0))
    z = 1.0 - 2.0 * i / n
    r = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    theta = phi * i
    return np.stack([r * np.cos(theta), r * np.sin(theta), z], axis=1)


def disc_samples(n: int) -> np.ndarray:
    """Deterministic sunflower samples on the unit disc (N,2)."""
    i = np.arange(n, dtype=float) + 0.5
    r = np.sqrt(i / n)
    theta = math.pi * (3.0 - math.sqrt(5.0)) * i
    return np.stack([r * np.cos(theta), r * np.sin(theta)], axis=1)


def angular_distance(a: float, b: float) -> float:
    """Smallest absolute difference between two angles (radians), in [0, pi]."""
    d = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return abs(d)
