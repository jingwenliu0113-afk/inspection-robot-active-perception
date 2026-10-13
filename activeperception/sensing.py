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
