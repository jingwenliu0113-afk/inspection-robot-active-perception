"""Sensor-derived quantities shared by every world (decision 007).

* ``zone_sample_points``: deterministic samples inside the inspection-zone cylinder.
* ``zone_visible_fraction_from_depth``: deployable obstruction proxy from a depth image.
  A zone sample counts as visible when the measured depth along its pixel ray reaches
  the point where that ray *enters* the zone cylinder (minus a tolerance). Anything
  inside the zone, including the target itself, therefore never lowers the value.
* ``gt_visibility_from_labels``: offline GT visibility from a full-scene and a
  clear-scene (occluders removed) semantic label image. Grader / oracle only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import disc_samples, project_points, ray_cylinder_entry
from .labeling import LabelingParams, visibility_score
from .types import CameraModel, InspectionZone, Pose

ZONE_DISC_SAMPLES = 48
ZONE_LEVELS = (1.0 / 6.0, 0.5, 5.0 / 6.0)  # fractions of the zone height
DEPTH_TOLERANCE_M = 0.05
DEPTH_KINDS = ("planar", "range")


def zone_sample_points(
    zone: InspectionZone, n_disc: int = ZONE_DISC_SAMPLES, levels=ZONE_LEVELS
) -> np.ndarray:
    disc = disc_samples(n_disc)
    pts = [
        np.column_stack(
            [
                zone.cx + zone.radius * disc[:, 0],
                zone.cy + zone.radius * disc[:, 1],
                np.full(len(disc), level * zone.height),
            ]
        )
        for level in levels
    ]
    return np.vstack(pts)


def zone_entry_depth(
    camera: CameraModel, pose: Pose, zone: InspectionZone, points: np.ndarray, depth_kind: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Zone points -> pixel coords, in-FOV mask, depth at which each ray enters the zone."""
    if depth_kind not in DEPTH_KINDS:
        raise ValueError(f"depth_kind must be one of {DEPTH_KINDS}")
    uv, planar, in_fov = project_points(camera, pose, points)
    origin = np.array(pose.position())
    rays = points - origin  # parameter 1 == the sample point
    s = ray_cylinder_entry(origin, rays, zone.cx, zone.cy, zone.radius, 0.0, zone.height)
    s = np.clip(np.where(np.isfinite(s), s, 1.0), 0.0, 1.0)
    if depth_kind == "planar":
        expected = s * planar
    else:
        expected = s * np.linalg.norm(rays, axis=1)
    return uv, in_fov, expected


def zone_visible_fraction_from_depth(
    depth: np.ndarray,
    camera: CameraModel,
    pose: Pose,
    zone: InspectionZone,
    depth_kind: str = "planar",
    tolerance: float = DEPTH_TOLERANCE_M,
) -> float:
    """Fraction of zone samples not obstructed by anything outside the zone.

    ``depth`` is (H, W) metres; +inf = no return (nothing in the way). Samples outside the
    field of view count as not visible, as in the synthetic world.
    """
    if depth.shape != (camera.height, camera.width):
        raise ValueError(f"depth shape {depth.shape} != camera {(camera.height, camera.width)}")
    pts = zone_sample_points(zone)
    uv, in_fov, expected = zone_entry_depth(camera, pose, zone, pts, depth_kind)
    visible = np.zeros(len(pts), dtype=bool)
    idx = np.flatnonzero(in_fov)
    cols = np.floor(uv[idx, 0]).astype(int)
    rows = np.floor(uv[idx, 1]).astype(int)
    measured = depth[rows, cols].astype(float)
    measured = np.where(np.isnan(measured), -np.inf, measured)  # NaN = invalid -> blocked
    visible[idx] = measured >= expected[idx] - tolerance
    return float(visible.mean())


@dataclass(frozen=True)
class LabelVisibility:
    visibility: float  # label-v1 GT visibility score
    vis_fraction: float  # visible object pixels / unoccluded object pixels
    area_frac: float  # unoccluded object pixels / image pixels
    visible_px: int
    full_px: int
    bbox_visible: tuple[int, int, int, int] | None  # x1, y1, x2, y2 (exclusive max)
    bbox_full: tuple[int, int, int, int] | None


def label_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    if not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def gt_visibility_from_labels(
    labels_full: np.ndarray,
    labels_clear: np.ndarray,
    object_label: int,
    params: LabelingParams | None = None,
) -> LabelVisibility:
    """label-v1 GT visibility from semantic label images (offline only)."""
    params = params or LabelingParams()
    if labels_full.shape != labels_clear.shape:
        raise ValueError("full / clear label images differ in shape")
    full_mask = labels_clear == object_label
    vis_mask = (labels_full == object_label) & full_mask
    full_px = int(full_mask.sum())
    visible_px = int(vis_mask.sum())
    if full_px == 0:
        return LabelVisibility(0.0, 0.0, 0.0, 0, 0, None, None)
    vis_fraction = visible_px / full_px
    area_frac = full_px / full_mask.size
    return LabelVisibility(
        visibility=visibility_score(vis_fraction, area_frac, params),
        vis_fraction=vis_fraction,
        area_frac=area_frac,
        visible_px=visible_px,
        full_px=full_px,
        bbox_visible=label_bbox(vis_mask),
        bbox_full=label_bbox(full_mask),
    )


# ---- depth-derived obstacle map (decision 008, rule-NBV v1) -------------------------
OBSTACLE_CELL_M = 0.05
OBSTACLE_MIN_HEIGHT_M = 0.05
OBSTACLE_ZONE_MARGIN_M = 0.03
OBSTACLE_MAX_RANGE_M = 4.0
OBSTACLE_PIXEL_STRIDE = 4


def obstacle_cells_from_depth(
    depth: np.ndarray,
    camera: CameraModel,
    pose: Pose,
    zone: InspectionZone,
    stride: int = OBSTACLE_PIXEL_STRIDE,
) -> tuple[tuple[int, int, int], ...]:
    """Height map cells (ix, iy, max height cm) of surfaces seen in a planar depth image.

    Ground (z <= 5 cm), anything inside the zone cylinder (+3 cm) and anything farther than
    4 m from the zone centre are dropped, so the target itself never enters the map.
    """
    from .geometry import rotation_matrix

    h, w = depth.shape
    rows = np.arange(stride // 2, h, stride)
    cols = np.arange(stride // 2, w, stride)
    uu, vv = np.meshgrid(cols + 0.5, rows + 0.5)
    d = depth[np.ix_(rows, cols)].astype(float)
    valid = np.isfinite(d) & (d > 0)
    f = camera.focal_px
    cam = np.stack([np.ones_like(uu), -(uu - w / 2.0) / f, -(vv - h / 2.0) / f], axis=-1)
    pts = (cam * d[..., None])[valid] @ rotation_matrix(pose.yaw, pose.pitch).T
    pts += np.array(pose.position())
    r = np.hypot(pts[:, 0] - zone.cx, pts[:, 1] - zone.cy)
    keep = (
        (pts[:, 2] > OBSTACLE_MIN_HEIGHT_M)
        & (r > zone.radius + OBSTACLE_ZONE_MARGIN_M)
        & (r < OBSTACLE_MAX_RANGE_M)
    )
    pts = pts[keep]
    if not len(pts):
        return ()
    ix = np.floor(pts[:, 0] / OBSTACLE_CELL_M).astype(int)
    iy = np.floor(pts[:, 1] / OBSTACLE_CELL_M).astype(int)
    hz = np.ceil(pts[:, 2] * 100.0).astype(int)
    best: dict[tuple[int, int], int] = {}
    for a, b, c in zip(ix.tolist(), iy.tolist(), hz.tolist(), strict=True):
        if c > best.get((a, b), -1):
            best[(a, b)] = c
    return tuple(sorted((a, b, c) for (a, b), c in best.items()))


def merge_obstacle_cells(maps) -> dict[tuple[int, int], int]:
    out: dict[tuple[int, int], int] = {}
    for cells in maps:
        for a, b, c in cells:
            if c > out.get((a, b), -1):
                out[(a, b)] = c
    return out


def predicted_zone_visibility(
    height_map: dict[tuple[int, int], int],
    camera: CameraModel,
    pose: Pose,
    zone: InspectionZone,
    n_steps: int = 64,
) -> float:
    """Fraction of zone samples a camera at ``pose`` would see past the known obstacles.

    Unknown cells count as free (optimistic); samples outside the field of view count as
    not visible, matching ``zone_visible_fraction_from_depth``.
    """
    pts = zone_sample_points(zone)
    _, _, in_fov = project_points(camera, pose, pts)
    if not height_map:
        return float(in_fov.mean())
    keys = np.array(list(height_map))
    lo = keys.min(axis=0)
    grid = np.zeros(tuple(keys.max(axis=0) - lo + 1), dtype=float)
    grid[keys[:, 0] - lo[0], keys[:, 1] - lo[1]] = np.array(list(height_map.values())) / 100.0
    origin = np.array(pose.position())
    t = np.linspace(0.0, 1.0, n_steps, endpoint=False)[1:]
    ray = origin + t[:, None, None] * (pts - origin)[None, :, :]  # (steps, N, 3)
    ix = np.floor(ray[..., 0] / OBSTACLE_CELL_M).astype(int) - lo[0]
    iy = np.floor(ray[..., 1] / OBSTACLE_CELL_M).astype(int) - lo[1]
    inside = (ix >= 0) & (iy >= 0) & (ix < grid.shape[0]) & (iy < grid.shape[1])
    heights = np.zeros(ix.shape)
    heights[inside] = grid[ix[inside], iy[inside]]
    outside_zone = np.hypot(ray[..., 0] - zone.cx, ray[..., 1] - zone.cy) > zone.radius
    blocked = ((ray[..., 2] < heights) & outside_zone).any(axis=0)
    return float((in_fov & ~blocked).mean())
