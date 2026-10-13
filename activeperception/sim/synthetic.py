"""Analytic synthetic world for development and correctness tests.

Geometry (gen-v2): the target is a vertical cylinder standing in for the fire hydrant;
occluders are axis-aligned pillars; the camera is a pinhole. GT visibility is the
visible fraction of the object's *projected* area (surface samples weighted by sample
area x cos(view angle)), times the label-v1 small-area penalty; this matches the
pixel-ratio definition used for Gazebo (decision 007). The synthetic detector maps
(visibility, projected area) to a confidence with seeded noise and a small
false-positive rate.

Everything is a deterministic function of (episode seed, viewpoint id), so the
observation at a viewpoint does not depend on the order of visits (teleport).

This world is NOT a source of reported results. Formal results come from the
Gazebo Harmonic world only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..episodes import stable_seed
from ..geometry import cylinder_surface_samples, project_points, segments_blocked
from ..labeling import LabelingParams, label_episode, visibility_score
from ..sensing import zone_sample_points
from ..types import (
    Detection,
    EpisodeGroundTruth,
    EpisodeSpec,
    Observation,
    Viewpoint,
)


@dataclass(frozen=True)
class SyntheticParams:
    proxy_radius: float = 0.15  # cylinder standing in for the hydrant body
    n_side_angles: int = 24
    n_side_levels: int = 8
    n_cap_samples: int = 16
    # detector model
    area_ref: float = 0.006  # area fraction at which detector quality saturates
    conf_slope: float = 9.0
    conf_midpoint: float = 0.35
    conf_noise_sd: float = 0.04
    detect_min_conf: float = 0.05
    false_positive_rate: float = 0.04
    false_positive_conf_range: tuple[float, float] = (0.05, 0.35)
    labeling: LabelingParams = LabelingParams()


class SyntheticWorld:
    name = "synthetic"

    def __init__(self, params: SyntheticParams | None = None):
        self.params = params or SyntheticParams()
        p = self.params
        self._unit_pts, self._normals = cylinder_surface_samples(
            p.n_side_angles, p.n_side_levels, p.n_cap_samples
        )
        n_side = p.n_side_angles * p.n_side_levels
        self._is_side = np.arange(len(self._unit_pts)) < n_side

    # ---- geometry -------------------------------------------------------
    def object_view(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> dict[str, float]:
        """GT visibility score, projected area fraction, bbox and centre for the object."""
        lay = spec.layout
        none = {"visibility": 0.0, "vis_fraction": 0.0, "area_frac": 0.0, "bbox": None}
        if not lay.object_present or lay.object_pose is None:
            return {**none, "center_uv": None}
        p = self.params
        cam = spec.camera
        r, h = p.proxy_radius, lay.object_height
        base = np.array([lay.object_pose.x, lay.object_pose.y, 0.0])
        pts = base + self._unit_pts * np.array([r, r, h])
        cam_pos = np.array(viewpoint.pose.position())
        to_cam = cam_pos - pts
        dist = np.linalg.norm(to_cam, axis=1)
        cos_view = np.einsum("ij,ij->i", self._normals, to_cam) / np.maximum(dist, 1e-9)
        sample_area = np.where(
            self._is_side,
            2 * math.pi * r * h / (p.n_side_angles * p.n_side_levels),
            math.pi * r * r / p.n_cap_samples,
        )
        weight = np.where(cos_view > 0.0, sample_area * cos_view, 0.0)
        if weight.sum() <= 0.0:
            return {**none, "center_uv": None}
        uv, _, in_fov = project_points(cam, viewpoint.pose, pts)
        blocked = segments_blocked(cam_pos, pts, lay.occluders)
        ok = (weight > 0.0) & in_fov & ~blocked
        vis_fraction = float(weight[ok].sum() / weight.sum())
        centre = base + np.array([0.0, 0.0, h / 2.0])
        d_c = float(np.linalg.norm(centre - cam_pos))
        sin_el = abs(cam_pos[2] - centre[2]) / max(d_c, 1e-9)
        cos_el = math.sqrt(max(0.0, 1.0 - sin_el * sin_el))
        area_m2 = 2 * r * h * cos_el + math.pi * r * r * sin_el
        area_frac = area_m2 * cam.focal_px**2 / max(d_c, 1e-9) ** 2 / (cam.width * cam.height)
        visibility = visibility_score(vis_fraction, area_frac, p.labeling)
        bbox = None
        center_uv = None
        if ok.any():
            sel = uv[ok]
            x1, y1 = sel.min(axis=0)
            x2, y2 = sel.max(axis=0)
            bbox = (float(x1), float(y1), float(x2), float(y2))
            center_uv = (float((x1 + x2) / 2 / cam.width), float((y1 + y2) / 2 / cam.height))
        return {
            "visibility": visibility,
            "vis_fraction": vis_fraction,
            "area_frac": area_frac * vis_fraction,
            "bbox": bbox,
            "center_uv": center_uv,
        }

    def zone_visible_fraction(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> float:
        """Fraction of zone samples in FOV whose line of sight no pillar blocks.

        Pillars never intrude the zone (gen-v2), so this equals the depth-camera
        definition in ``sensing.zone_visible_fraction_from_depth`` (decision 007).
        """
        pts = zone_sample_points(spec.zone)
        cam_pos = np.array(viewpoint.pose.position())
        _, _, in_fov = project_points(spec.camera, viewpoint.pose, pts)
        blocked = segments_blocked(cam_pos, pts, spec.layout.occluders)
        return float((in_fov & ~blocked).mean())

    def obstacle_cells(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> tuple:
        """Analytic stand-in for ``sensing.obstacle_cells_from_depth`` (dev / tests only).

        A pillar contributes its whole footprint (5 cm cells, top height) when its centre
        at half height is in the field of view and not hidden behind another pillar.
        """
        from ..sensing import OBSTACLE_CELL_M

        cam_pos = np.array(viewpoint.pose.position())
        cells: dict[tuple[int, int], int] = {}
        boxes = spec.layout.occluders
        for i, b in enumerate(boxes):
            centre = np.array([[b.cx, b.cy, b.cz]])
            _, _, in_fov = project_points(spec.camera, viewpoint.pose, centre)
            others = [o for j, o in enumerate(boxes) if j != i]
            if not in_fov[0] or segments_blocked(cam_pos, centre, others)[0]:
                continue
            x0 = int(np.floor((b.cx - b.sx / 2) / OBSTACLE_CELL_M))
            x1 = int(np.floor((b.cx + b.sx / 2) / OBSTACLE_CELL_M))
            y0 = int(np.floor((b.cy - b.sy / 2) / OBSTACLE_CELL_M))
            y1 = int(np.floor((b.cy + b.sy / 2) / OBSTACLE_CELL_M))
            h = int(np.ceil(b.sz * 100.0))
            for ix in range(x0, x1 + 1):
                for iy in range(y0, y1 + 1):
                    cells[(ix, iy)] = max(h, cells.get((ix, iy), 0))
        return tuple(sorted((a, c, h) for (a, c), h in cells.items()))

    def location_visibility(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> tuple:
        """Analytic counterpart of ``sensing.location_visibility_from_depth``."""
        from ..geometry import ray_cylinder_entry
        from ..sensing import ZONE_LEVELS, location_axis_points, location_grid

        grid = location_grid(spec.zone)
        pts = location_axis_points(spec.zone, grid)
        cam_pos = np.array(viewpoint.pose.position())
        _, _, in_fov = project_points(spec.camera, viewpoint.pose, pts)
        blocked = segments_blocked(cam_pos, pts, spec.layout.occluders)
        lay = spec.layout
        if lay.object_present and lay.object_pose is not None:
            s = ray_cylinder_entry(
                cam_pos,
                pts - cam_pos,
                lay.object_pose.x,
                lay.object_pose.y,
                self.params.proxy_radius,
                0.0,
                lay.object_height,
            )
            blocked |= s < 1.0 - 1e-9
        seen = (in_fov & ~blocked).reshape(len(grid), len(ZONE_LEVELS)).mean(axis=1)
        return tuple(float(v) for v in seen)

    # ---- oracle pass ------------------------------------------------------
    def ground_truth(self, spec: EpisodeSpec) -> EpisodeGroundTruth:
        vis_init = self.object_view(spec, spec.initial_viewpoint)["visibility"]
        vis_by = {
            vp.id: self.object_view(spec, vp)["visibility"] for vp in spec.candidate_viewpoints
        }
        zone_by = {vp.id: self.zone_visible_fraction(spec, vp) for vp in spec.candidate_viewpoints}
        zone_by[spec.initial_viewpoint.id] = self.zone_visible_fraction(
            spec, spec.initial_viewpoint
        )
        return label_episode(
            spec.episode_id,
            spec.layout.object_present,
            vis_init,
            vis_by,
            zone_by,
            self.params.labeling,
        )

    # ---- deployable observation ------------------------------------------
    def observe(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> Observation:
        p = self.params
        rng = np.random.default_rng(stable_seed("obs", spec.seed, viewpoint.id))
        view = self.object_view(spec, viewpoint)
        detections: list[Detection] = []
        quality = view["visibility"] * min(1.0, view["area_frac"] / p.area_ref)
        if quality > 0.0:
            logit = p.conf_slope * (quality - p.conf_midpoint)
            conf = 1.0 / (1.0 + math.exp(-logit)) + rng.normal(0.0, p.conf_noise_sd)
            conf = float(min(max(conf, 0.0), 1.0))
            if conf >= p.detect_min_conf and view["bbox"] is not None:
                detections.append(
                    Detection(
                        confidence=conf,
                        bbox=view["bbox"],
                        area_frac=float(view["area_frac"]),
                        center_uv=view["center_uv"],
                    )
                )
        if not detections and rng.uniform() < p.false_positive_rate:
            conf = float(rng.uniform(*p.false_positive_conf_range))
            w, h = spec.camera.width, spec.camera.height
            u, v = rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)
            size = rng.uniform(0.02, 0.06)
            bbox = (u * w - size * w, v * h - size * h, u * w + size * w, v * h + size * h)
            detections.append(
                Detection(
                    confidence=conf, bbox=bbox, area_frac=float(4 * size * size), center_uv=(u, v)
                )
            )
        return Observation(
            viewpoint_id=viewpoint.id,
            viewpoint=viewpoint,
            detections=tuple(detections),
            zone_visible_fraction=self.zone_visible_fraction(spec, viewpoint),
            timestamp=0.0,
            image_ref=None,
            obstacle_cells=self.obstacle_cells(spec, viewpoint),
            location_visibility=self.location_visibility(spec, viewpoint),
            meta={"world": self.name},
        )
