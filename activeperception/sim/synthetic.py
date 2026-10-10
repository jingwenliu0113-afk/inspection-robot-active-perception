"""Analytic synthetic world for development and correctness tests.

Geometry: the object is a sphere; occluders are axis-aligned pillars; the camera
is a pinhole. GT visibility is the fraction of camera-facing surface samples that
are inside the field of view and not blocked by any pillar, scaled down when the
projected area is tiny. The synthetic detector maps (visibility, projected area)
to a confidence with seeded noise and a small false-positive rate.

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
from ..geometry import disc_samples, fibonacci_sphere, project_points, segments_blocked
from ..labeling import LabelingParams, label_episode
from ..types import (
    Detection,
    EpisodeGroundTruth,
    EpisodeSpec,
    Observation,
    Viewpoint,
)


@dataclass(frozen=True)
class SyntheticParams:
    n_surface_samples: int = 128
    n_zone_samples: int = 48
    min_area_frac: float = 0.002  # projected area below this starts to penalise visibility
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
        self._sphere = fibonacci_sphere(self.params.n_surface_samples)
        self._disc = disc_samples(self.params.n_zone_samples)

    # ---- geometry -------------------------------------------------------
    def object_view(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> dict[str, float]:
        """GT visibility score, projected area fraction, bbox and centre for the object."""
        lay = spec.layout
        if not lay.object_present or lay.object_pose is None:
            return {"visibility": 0.0, "area_frac": 0.0, "bbox": None, "center_uv": None}
        cam = spec.camera
        center = np.array(lay.object_pose.position())
        cam_pos = np.array(viewpoint.pose.position())
        normals = self._sphere
        facing = normals @ (cam_pos - center) > 0.0
        pts = center + lay.object_radius * normals
        uv, depth, in_fov = project_points(cam, viewpoint.pose, pts)
        blocked = segments_blocked(cam_pos, pts, lay.occluders)
        n_facing = int(facing.sum())
        if n_facing == 0:
            return {"visibility": 0.0, "area_frac": 0.0, "bbox": None, "center_uv": None}
        ok = facing & in_fov & ~blocked
        vis_fraction = float(ok.sum()) / n_facing
        dist = float(np.linalg.norm(center - cam_pos))
        r_px = cam.focal_px * lay.object_radius / max(dist, 1e-6)
        area_frac = math.pi * r_px * r_px / (cam.width * cam.height)
        area_factor = min(1.0, area_frac / self.params.min_area_frac)
        visibility = vis_fraction * area_factor
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
        """Fraction of zone sample points in FOV with an unblocked line of sight.

        This is what a depth camera would tell a deployed system about whether the
        inspection zone is obstructed from this viewpoint.
        """
        z = spec.zone
        pts = np.column_stack(
            [
                z.cx + z.radius * self._disc[:, 0],
                z.cy + z.radius * self._disc[:, 1],
                np.full(len(self._disc), z.cz),
            ]
        )
        cam_pos = np.array(viewpoint.pose.position())
        _, _, in_fov = project_points(spec.camera, viewpoint.pose, pts)
        blocked = segments_blocked(cam_pos, pts, spec.layout.occluders)
        return float((in_fov & ~blocked).mean())

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
            meta={"world": self.name},
        )
