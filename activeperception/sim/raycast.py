"""Analytic ray-cast renderer of an episode's proxy geometry (numpy, CPU).

Renders planar depth (metres along the optical axis, +inf = no return) and semantic
labels with the Gazebo label ids for: the ground plane, the axis-aligned pillars and a
vertical cylinder standing in for the target object.

Uses: tests of the depth / label processing in ``activeperception.sensing``, and the
pilot cross-check of the Gazebo camera intrinsics, extrinsics and depth convention
(decision 007). Pixel (row i, col j) is the ray through image point (j + 0.5, i + 0.5),
the same convention ``geometry.project_points`` uses for in-FOV tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry import ray_box_entry, ray_cylinder_entry, rotation_matrix
from ..types import Box, CameraModel, EpisodeSpec, Pose
from .sdf import LABEL_GROUND, LABEL_OBJECT, LABEL_PILLAR

LABEL_BACKGROUND = 0
FAR_CLIP_M = 20.0


@dataclass(frozen=True)
class CylinderProxy:
    cx: float
    cy: float
    radius: float
    height: float


def pixel_rays(camera: CameraModel, pose: Pose) -> tuple[np.ndarray, np.ndarray]:
    """Camera origin and world-frame ray directions (H*W, 3) whose camera-x component is 1.

    With that scaling the ray parameter of a hit equals its planar depth.
    """
    f = camera.focal_px
    u = np.arange(camera.width) + 0.5
    v = np.arange(camera.height) + 0.5
    uu, vv = np.meshgrid(u, v)
    cam = np.stack(
        [
            np.ones(uu.size),
            -(uu.ravel() - camera.width / 2.0) / f,
            -(vv.ravel() - camera.height / 2.0) / f,
        ],
        axis=1,
    )
    dirs = cam @ rotation_matrix(pose.yaw, pose.pitch).T
    return np.array(pose.position()), dirs


def render(
    camera: CameraModel,
    pose: Pose,
    occluders: tuple[Box, ...] | list[Box],
    obj: CylinderProxy | None,
    far: float = FAR_CLIP_M,
) -> tuple[np.ndarray, np.ndarray]:
    origin, dirs = pixel_rays(camera, pose)
    depth = np.full(len(dirs), np.inf)
    labels = np.full(len(dirs), LABEL_BACKGROUND, dtype=np.uint8)

    def take(t: np.ndarray, label: int) -> None:
        closer = (t > 0.0) & (t < depth)
        depth[closer] = t[closer]
        labels[closer] = label

    with np.errstate(divide="ignore", invalid="ignore"):
        t_ground = np.where(dirs[:, 2] < 0.0, -origin[2] / dirs[:, 2], np.inf)
    take(t_ground, LABEL_GROUND)
    for box in occluders:
        take(ray_box_entry(origin, dirs, box), LABEL_PILLAR)
    if obj is not None:
        take(
            ray_cylinder_entry(origin, dirs, obj.cx, obj.cy, obj.radius, 0.0, obj.height),
            LABEL_OBJECT,
        )
    beyond = depth > far
    depth[beyond] = np.inf
    labels[beyond] = LABEL_BACKGROUND
    shape = (camera.height, camera.width)
    return depth.reshape(shape).astype(np.float32), labels.reshape(shape)


def object_proxy(spec: EpisodeSpec, proxy_radius: float) -> CylinderProxy | None:
    lay = spec.layout
    if not lay.object_present or lay.object_pose is None:
        return None
    return CylinderProxy(lay.object_pose.x, lay.object_pose.y, proxy_radius, lay.object_height)


def render_spec(
    spec: EpisodeSpec, pose: Pose, proxy_radius: float, clear: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Depth + labels of the episode proxy scene; ``clear`` drops the pillars (GT pass)."""
    occluders = () if clear else spec.layout.occluders
    return render(spec.camera, pose, occluders, object_proxy(spec, proxy_radius))


LABEL_COLOURS = {
    LABEL_BACKGROUND: (150, 180, 210),
    LABEL_GROUND: (180, 180, 170),
    LABEL_PILLAR: (110, 110, 110),
    LABEL_OBJECT: (200, 20, 20),
}


def write_proxy_frames(spec: EpisodeSpec, out_dir, proxy_radius: float) -> None:
    """Write a ``render-v1`` frame-store entry from the proxy geometry (tests / dev only)."""
    from pathlib import Path

    from ..framestore import encode_depth_mm, write_episode_frames
    from ..serialize import spec_digest

    vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
    rgb, depth_mm, labels, clear = [], [], [], []
    for vp in vps:
        d, lab = render_spec(spec, vp.pose, proxy_radius)
        img = np.zeros(lab.shape + (3,), dtype=np.uint8)
        for value, colour in LABEL_COLOURS.items():
            img[lab == value] = colour
        rgb.append(img)
        depth_mm.append(encode_depth_mm(d))
        labels.append(lab)
        if spec.layout.object_present:
            clear.append(render_spec(spec, vp.pose, proxy_radius, clear=True)[1])
    stamps = np.arange(1, len(vps) + 1, dtype=np.int64) * 100_000_000
    arrays = {
        "vp_ids": np.array([vp.id for vp in vps], dtype=np.int16),
        "poses": np.array([[v.pose.x, v.pose.y, v.pose.z, v.pose.yaw, v.pose.pitch] for v in vps]),
        "rgb": np.stack(rgb),
        "depth_mm": np.stack(depth_mm),
        "labels": np.stack(labels),
        "stamps_ns": stamps,
        "t_ref_ns": stamps - 50_000_000,
    }
    if clear:
        arrays["labels_clear"] = np.stack(clear)
    meta = {
        "episode_id": spec.episode_id,
        "spec_digest": spec_digest(spec),
        "generator_version": spec.generator_version,
        "renderer": "raycast-proxy",
        "depth_kind": "planar",
        "settle_ns": 50_000_000,  # stamps are written 50 ms after t_ref
    }
    write_episode_frames(Path(out_dir) / f"{spec.episode_id}.npz", arrays, meta)
