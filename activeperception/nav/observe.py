"""Deployable observations of a robot stop (decisions 015 / 016). Shared by the B0 analysis
(Mac) and the B1 closed-loop driver (container).

``observation`` / ``observation_d016`` build the decision input from the onboard depth, the
detector output and a camera pose derived from the localisation estimate; neither takes a
ground-truth argument. ``gt_camera_pose`` exists for scoring only.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from ..sensing import (
    location_visibility_from_depth,
    obstacle_cells_from_depth,
    zone_visible_fraction_from_depth,
)
from ..types import Detection, EpisodeSpec, Observation, Pose, Viewpoint
from . import scene
from .robot import BASE_REST_Z, CAMERA_ABOVE_BASE


def _rot(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = (f(a) for a in (roll, pitch, yaw) for f in (math.cos, math.sin))
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1.0]])
    ry = np.array([[cp, 0, sp], [0, 1.0, 0], [-sp, 0, cp]])
    rx = np.array([[1.0, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def camera_pose(
    x: float, y: float, yaw: float, z: float = BASE_REST_Z, roll: float = 0.0, pitch: float = 0.0
) -> tuple[Pose, float]:
    """Mast camera pose from a base pose; returns (pose, residual roll about the optical axis).

    ``Pose`` has no roll; with a level base the residual is 0.
    """
    r_base = _rot(roll, pitch, yaw)
    pos = np.array([x, y, z]) + r_base @ np.array([0.0, 0.0, CAMERA_ABOVE_BASE])
    r_cam = r_base @ _rot(0.0, scene.MAST_PITCH, 0.0)
    f, left = r_cam @ np.array([1.0, 0, 0]), r_cam @ np.array([0, 1.0, 0])
    cam_yaw = math.atan2(f[1], f[0])
    cam_pitch = -math.asin(max(-1.0, min(1.0, f[2])))
    level_left = np.array([-math.sin(cam_yaw), math.cos(cam_yaw), 0.0])
    resid = math.atan2(
        float(np.dot(np.cross(level_left, left), f)), float(np.dot(level_left, left))
    )
    return Pose(float(pos[0]), float(pos[1]), float(pos[2]), cam_yaw, cam_pitch), resid


def deployable_camera_pose(estimate: dict) -> Pose:
    """Camera pose the robot believes it has: AMCL (x, y, yaw), level base at rest height."""
    return camera_pose(estimate["x"], estimate["y"], estimate["yaw"])[0]


def gt_camera_pose(gt: dict) -> tuple[Pose, float]:
    return camera_pose(gt["x"], gt["y"], gt["yaw"], gt["z"], gt["roll"], gt["pitch"])


def observation(
    spec: EpisodeSpec, index: int, depth: np.ndarray, dets: tuple[Detection, ...], pose: Pose
) -> Observation:
    """Decision input from deployable data only (no ground-truth argument)."""
    z = spec.zone
    vp = Viewpoint(
        id=index,
        pose=pose,
        azimuth=math.atan2(pose.y - z.cy, pose.x - z.cx) % (2 * math.pi),
        radius=math.hypot(pose.x - z.cx, pose.y - z.cy),
        height=pose.z,
    )
    return Observation(
        viewpoint_id=index,
        viewpoint=vp,
        detections=dets,
        zone_visible_fraction=zone_visible_fraction_from_depth(depth, spec.camera, pose, z),
        timestamp=float(index),
        obstacle_cells=obstacle_cells_from_depth(depth, spec.camera, pose, z),
        location_visibility=location_visibility_from_depth(depth, spec.camera, pose, z),
    )


def observation_d016(
    spec: EpisodeSpec, index: int, depth: np.ndarray, dets: tuple[Detection, ...], estimate: Pose
):
    """decision 016 decision input: refined pose + pose-robust see-through (deployable only)."""
    from .localize import deployable_pose_and_visibility, map_outlines

    pose, vis, ref = deployable_pose_and_visibility(
        depth, spec.camera, estimate, spec.zone, map_outlines(spec)
    )
    obs = dataclasses.replace(observation(spec, index, depth, dets, pose), location_visibility=vis)
    return obs, ref
