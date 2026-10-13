"""Gazebo replay world (decision 007): observations come from the frame store.

``observe`` reads only deployable data: the RGB frame's cached detections and the depth
image (-> ``zone_visible_fraction``). ``ground_truth`` reads the semantic labels of the full
and clear passes; it is the offline oracle pass and is never called by deployable
policies (``tests/test_leakage.py``).
"""

from __future__ import annotations

import numpy as np

from ..detector.cache import DetectionCache
from ..framestore import FrameStore
from ..labeling import LabelingParams, label_episode
from ..sensing import (
    gt_visibility_from_labels,
    location_visibility_from_depth,
    obstacle_cells_from_depth,
    zone_visible_fraction_from_depth,
)
from ..serialize import spec_digest
from ..types import EpisodeGroundTruth, EpisodeSpec, Observation, Viewpoint
from .sdf import LABEL_OBJECT


class FrameMismatchError(RuntimeError):
    pass


class GazeboReplayWorld:
    name = "gazebo"

    def __init__(
        self,
        store: FrameStore,
        detections: DetectionCache | None,
        labeling: LabelingParams | None = None,
        depth_kind: str = "planar",
    ):
        self.store = store
        self.detections = detections
        self.labeling = labeling or LabelingParams()
        self.depth_kind = depth_kind
        self._zone_cache: dict[tuple[str, int], float] = {}
        self._obstacle_cache: dict[tuple[str, int], tuple] = {}
        # observations are immutable functions of (episode, viewpoint) -> memoise them, so a
        # parameter sweep does not re-read frames (the frame store LRU is small)
        self._obs_cache: dict[tuple[str, int], Observation] = {}
        self._checked: set[str] = set()

    def _frames(self, spec: EpisodeSpec):
        frames = self.store.episode(spec.episode_id)
        if spec.episode_id not in self._checked:
            if frames.meta.get("spec_digest") != spec_digest(spec):
                raise FrameMismatchError(f"{spec.episode_id}: frames come from another spec")
            self._checked.add(spec.episode_id)
        return frames

    def zone_visible_fraction(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> float:
        key = (spec.episode_id, viewpoint.id)
        if key not in self._zone_cache:
            frames = self._frames(spec)
            p = viewpoint.pose
            expected = np.array([p.x, p.y, p.z, p.yaw, p.pitch])
            if not np.allclose(frames.pose(viewpoint.id), expected, atol=1e-9):
                raise FrameMismatchError(f"{spec.episode_id} vp {viewpoint.id}: pose differs")
            self._zone_cache[key] = zone_visible_fraction_from_depth(
                frames.depth(viewpoint.id), spec.camera, viewpoint.pose, spec.zone, self.depth_kind
            )
        return self._zone_cache[key]

    def obstacle_cells(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> tuple:
        key = (spec.episode_id, viewpoint.id)
        if key not in self._obstacle_cache:
            self.zone_visible_fraction(spec, viewpoint)  # spec digest + pose checks
            self._obstacle_cache[key] = obstacle_cells_from_depth(
                self._frames(spec).depth(viewpoint.id), spec.camera, viewpoint.pose, spec.zone
            )
        return self._obstacle_cache[key]

    def observe(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> Observation:
        if self.detections is None:
            raise RuntimeError("replay world has no detection cache; observe() needs one")
        key = (spec.episode_id, viewpoint.id)
        if key in self._obs_cache:  # built only after the spec digest check passed
            return self._obs_cache[key]
        frames = self._frames(spec)
        self._obs_cache[key] = Observation(
            viewpoint_id=viewpoint.id,
            viewpoint=viewpoint,
            detections=self.detections.get(spec.episode_id, viewpoint.id),
            zone_visible_fraction=self.zone_visible_fraction(spec, viewpoint),
            timestamp=frames.stamp_s(viewpoint.id),
            image_ref=f"{spec.episode_id}#{viewpoint.id}",
            obstacle_cells=self.obstacle_cells(spec, viewpoint),
            location_visibility=location_visibility_from_depth(
                frames.depth(viewpoint.id), spec.camera, viewpoint.pose, spec.zone
            ),
            meta={"world": self.name, "detector": self.detections.detector},
        )
        return self._obs_cache[key]

    def object_visibility(self, spec: EpisodeSpec, viewpoint: Viewpoint):
        """Offline only: label-based GT visibility of the object from one viewpoint."""
        frames = self._frames(spec)
        clear = frames.labels_clear(viewpoint.id)
        if not spec.layout.object_present or clear is None:
            return None
        return gt_visibility_from_labels(
            frames.labels(viewpoint.id), clear, LABEL_OBJECT, self.labeling
        )

    def ground_truth(self, spec: EpisodeSpec) -> EpisodeGroundTruth:
        vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
        vis = {}
        for vp in vps:
            lv = self.object_visibility(spec, vp)
            vis[vp.id] = 0.0 if lv is None else lv.visibility
        if spec.layout.object_present and all(v == 0.0 for v in vis.values()):
            # a present object that is invisible from every rendered view is possible, but
            # if the clear pass is also empty something is wrong with the render
            frames = self._frames(spec)
            if not any((frames.labels_clear(vp.id) == LABEL_OBJECT).any() for vp in vps):
                raise FrameMismatchError(f"{spec.episode_id}: object never rendered")
        zone = {vp.id: self.zone_visible_fraction(spec, vp) for vp in vps}
        initial = spec.initial_viewpoint.id
        return label_episode(
            spec.episode_id,
            spec.layout.object_present,
            vis[initial],
            {k: v for k, v in vis.items() if k != initial},
            zone,
            self.labeling,
        )


def make_peek(world, specs):
    """``peek(episode_id, viewpoint_id) -> Observation`` for the oracle-v2 upper bound."""
    by_id = {s.episode_id: s for s in specs}

    def peek(episode_id: str, viewpoint_id: int):
        spec = by_id[episode_id]
        vp = (
            spec.initial_viewpoint
            if viewpoint_id == spec.initial_viewpoint.id
            else spec.deployable().candidate(viewpoint_id)
        )
        return world.observe(spec, vp)

    return peek
