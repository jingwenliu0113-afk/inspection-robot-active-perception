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


def ray_box_entry(origin: np.ndarray, dirs: np.ndarray, box: Box) -> np.ndarray:
    """Entry parameter s >= 0 of rays origin + s * dirs into an axis-aligned box (slab test).

    Returns 0 when the origin is inside the box and +inf when the ray misses it.
    """
    o = np.asarray(origin, dtype=float).reshape(1, 3)
    d = np.asarray(dirs, dtype=float).reshape(-1, 3)
    lo, hi = box_bounds(box)
    zero = d == 0.0
    inside = (o >= lo) & (o <= hi)
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (lo - o) / d
        t2 = (hi - o) / d
    t_near = np.minimum(t1, t2)
    t_far = np.maximum(t1, t2)
    # axis-parallel rays: inside the slab -> no constraint, outside -> can never hit
    t_near = np.where(zero, np.where(inside, -np.inf, np.inf), t_near)
    t_far = np.where(zero, np.where(inside, np.inf, -np.inf), t_far)
    tmin = t_near.max(axis=1)
    tmax = t_far.min(axis=1)
    hit = (tmax >= tmin) & (tmax >= 0.0)
    return np.where(hit, np.maximum(tmin, 0.0), np.inf)


def segments_blocked(origin: np.ndarray, targets: np.ndarray, boxes: list[Box] | tuple[Box, ...]):
    """For each segment origin->target, True if it intersects any box."""
    o = np.asarray(origin, dtype=float).reshape(3)
    d = np.asarray(targets, dtype=float).reshape(-1, 3) - o
    blocked = np.zeros(len(d), dtype=bool)
    for box in boxes:
        blocked |= ray_box_entry(o, d, box) <= 1.0
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


def cylinder_surface_samples(
    n_angles: int, n_levels: int, n_cap: int
) -> tuple[np.ndarray, np.ndarray]:
    """Unit cylinder (radius 1, z in [0, 1]) side + top-cap samples and outward normals.

    The bottom cap is omitted: the cylinder stands on the ground.
    """
    ang = 2 * math.pi * (np.arange(n_angles) + 0.5) / n_angles
    lev = (np.arange(n_levels) + 0.5) / n_levels
    a, z = np.meshgrid(ang, lev, indexing="ij")
    side = np.stack([np.cos(a).ravel(), np.sin(a).ravel(), z.ravel()], axis=1)
    side_n = np.stack([np.cos(a).ravel(), np.sin(a).ravel(), np.zeros(a.size)], axis=1)
    disc = disc_samples(n_cap)
    cap = np.column_stack([disc, np.ones(len(disc))])
    cap_n = np.tile([0.0, 0.0, 1.0], (len(disc), 1))
    return np.vstack([side, cap]), np.vstack([side_n, cap_n])


def ray_cylinder_entry(
    origin: np.ndarray,
    dirs: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    z0: float,
    z1: float,
) -> np.ndarray:
    """Entry parameter s >= 0 of rays origin + s * dirs into a vertical cylinder.

    ``dirs`` need not be unit length; s is in units of each row of ``dirs``. Returns 0
    when the origin is inside, +inf when the ray misses.
    """
    o = np.asarray(origin, dtype=float).reshape(3)
    d = np.asarray(dirs, dtype=float).reshape(-1, 3)
    ox, oy = o[0] - cx, o[1] - cy
    a = d[:, 0] ** 2 + d[:, 1] ** 2
    b = 2.0 * (ox * d[:, 0] + oy * d[:, 1])
    c = ox * ox + oy * oy - radius * radius
    lo = np.full(len(d), -np.inf)
    hi = np.full(len(d), np.inf)
    radial = a > 1e-12
    disc = b * b - 4.0 * a * c
    with np.errstate(invalid="ignore", divide="ignore"):
        sq = np.sqrt(np.where(disc >= 0.0, disc, 0.0))
        t1 = (-b - sq) / (2.0 * a)
        t2 = (-b + sq) / (2.0 * a)
    miss = (radial & (disc < 0.0)) | (~radial & (c > 0.0))
    lo = np.where(radial, t1, lo)
    hi = np.where(radial, t2, hi)
    vertical = np.abs(d[:, 2]) > 1e-12
    with np.errstate(invalid="ignore", divide="ignore"):
        tz_a = (z0 - o[2]) / d[:, 2]
        tz_b = (z1 - o[2]) / d[:, 2]
    tz_lo = np.where(vertical, np.minimum(tz_a, tz_b), -np.inf)
    tz_hi = np.where(vertical, np.maximum(tz_a, tz_b), np.inf)
    miss |= ~vertical & ((o[2] < z0) | (o[2] > z1))
    entry = np.maximum(lo, tz_lo)
    exit_ = np.minimum(hi, tz_hi)
    hit = ~miss & (entry <= exit_) & (exit_ >= 0.0)
    return np.where(hit, np.maximum(entry, 0.0), np.inf)


def pose_quaternion(yaw: float, pitch: float) -> tuple[float, float, float, float]:
    """(w, x, y, z) of Rz(yaw) @ Ry(pitch) (roll = 0), matching ``rotation_matrix``."""
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    return cy * cp, -sy * sp, cy * sp, sy * cp
