"""Frozen schemas shared by generator, worlds, policies, grader and metrics.

Leakage boundary
----------------
``EpisodeSpec`` carries the full scene layout (object pose, occluders). Deployable
policies never receive it. They receive ``DeployableEpisode`` (zone, camera,
initial viewpoint, candidate viewpoints) plus the observation history only.
``EpisodeGroundTruth`` is produced by a world's oracle pass and is used only by
the grader and by the Oracle NBV upper bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GroundTruthState(StrEnum):
    VISIBLE = "visible"  # object present and observable from the initial viewpoint
    UNOBSERVABLE = "unobservable"  # object present but not reliably observable initially
    ABSENT = "absent"  # object not present


class Decision(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    INCONCLUSIVE = "inconclusive"


class Split(StrEnum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"
    PILOT = "pilot"
    DETSEL = "detsel"  # detector-selection data (decision 005), never train / val / test
    HOLDOUT = "holdout"  # v1 vs v2 comparison data (decision 011), never used for development


@dataclass(frozen=True)
class Pose:
    """Position in metres and orientation (yaw about +z, then pitch about +y).

    ROS convention: positive pitch tilts the optical axis downwards.
    """

    x: float
    y: float
    z: float
    yaw: float
    pitch: float = 0.0

    def position(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class CameraModel:
    width: int = 640
    height: int = 480
    hfov: float = math.radians(60.0)

    @property
    def focal_px(self) -> float:
        return (self.width / 2.0) / math.tan(self.hfov / 2.0)


@dataclass(frozen=True)
class InspectionZone:
    """The region the task asks us to inspect. Known at deployment time.

    A vertical cylinder standing on the ground: centre (cx, cy), ``radius``, z in
    [0, ``height``]. ``cz`` is the height every viewpoint looks at.
    """

    cx: float
    cy: float
    cz: float
    radius: float
    height: float


@dataclass(frozen=True)
class Viewpoint:
    """A candidate camera pose. ``azimuth`` is the bearing from the zone centre."""

    id: int
    pose: Pose
    azimuth: float
    radius: float
    height: float


@dataclass(frozen=True)
class Box:
    """Axis-aligned occluder: centre and full extents."""

    cx: float
    cy: float
    cz: float
    sx: float
    sy: float
    sz: float


@dataclass(frozen=True)
class SceneLayout:
    """Simulator-facing scene content. Never exposed to deployable policies."""

    object_present: bool
    object_pose: Pose | None  # base of the object on the ground; yaw = heading
    object_model: str  # Gazebo model name (gazebo/models/<object_model>)
    object_radius: float  # footprint circumradius (placement; synthetic proxy bound)
    object_height: float
    occluders: tuple[Box, ...]


@dataclass(frozen=True)
class DeployableEpisode:
    """Everything a deployable policy is allowed to know about an episode."""

    episode_id: str
    zone: InspectionZone
    camera: CameraModel
    initial_viewpoint: Viewpoint
    candidate_viewpoints: tuple[Viewpoint, ...]

    def candidate(self, viewpoint_id: int) -> Viewpoint:
        for vp in self.candidate_viewpoints:
            if vp.id == viewpoint_id:
                return vp
        raise KeyError(f"unknown candidate viewpoint id {viewpoint_id}")


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: str
    namespace: str
    scene_group: int
    variant: int
    seed: int
    split: Split
    generator_version: str
    zone: InspectionZone
    camera: CameraModel
    initial_viewpoint: Viewpoint
    candidate_viewpoints: tuple[Viewpoint, ...]
    layout: SceneLayout

    def deployable(self) -> DeployableEpisode:
        return DeployableEpisode(
            episode_id=self.episode_id,
            zone=self.zone,
            camera=self.camera,
            initial_viewpoint=self.initial_viewpoint,
            candidate_viewpoints=self.candidate_viewpoints,
        )


@dataclass(frozen=True)
class EpisodeGroundTruth:
    """Offline labels produced by a world's oracle pass (scoring / oracle only)."""

    episode_id: str
    object_present: bool
    state: GroundTruthState
    revealable: bool  # some candidate viewpoint has GT visibility >= threshold
    visibility_initial: float
    visibility_by_viewpoint: dict[int, float]  # candidate id -> GT visibility score
    zone_visible_by_viewpoint: dict[int, float]  # candidate id -> GT zone-visible fraction
    labeling_version: str


@dataclass(frozen=True)
class Detection:
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    area_frac: float  # bbox area / image area
    center_uv: tuple[float, float]  # normalised [0, 1] image coordinates


@dataclass(frozen=True)
class Observation:
    """What the deployable system gets after teleporting to a viewpoint.

    ``zone_visible_fraction`` is derived from the depth image (fraction of zone
    sample points whose line of sight is not blocked). It is sensor-derived and
    available at deployment time; it is not an object-occlusion label.
    """

    viewpoint_id: int
    viewpoint: Viewpoint
    detections: tuple[Detection, ...]
    zone_visible_fraction: float
    timestamp: float
    image_ref: str | None = None
    # depth-derived obstacle height map of this view (decision 008): (ix, iy, height_cm)
    # cells of 5 cm outside the zone cylinder; deployable sensor data, not GT
    obstacle_cells: tuple[tuple[int, int, int], ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def max_confidence(self) -> float:
        return max((d.confidence for d in self.detections), default=0.0)


@dataclass(frozen=True)
class DecisionOutput:
    decision: Decision
    confidence: float
    features: dict[str, float]


@dataclass(frozen=True)
class EpisodeRecord:
    """One method's run on one episode at one budget."""

    episode_id: str
    policy: str
    budget: int
    run_seed: int
    viewpoint_sequence: tuple[int, ...]
    observations: tuple[Observation, ...]
    decision: Decision
    confidence: float
    features: dict[str, float]

    @property
    def viewpoints_used(self) -> int:
        return len(self.observations)


INITIAL_VIEWPOINT_ID = -1
