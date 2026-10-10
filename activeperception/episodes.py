"""Seeded episode generator, candidate viewpoints and split assignment.

Independence guarantees (tested in ``tests/test_leakage.py``):

* Candidate viewpoints and the initial viewpoint are a function of
  ``(namespace, generator_version, scene_group)`` only. They never depend on the
  object (present/absent, pose) or on the occluder layout.
* Object placement uses a separate random stream keyed by the variant.
* Split is a function of ``(namespace, scene_group)``. All variants of a scene
  group land in the same split, so near-duplicate scenes never straddle splits.
* The ``pilot`` namespace is disjoint from the formal namespace at the seed level.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from .geometry import look_at_pose
from .types import (
    INITIAL_VIEWPOINT_ID,
    Box,
    CameraModel,
    EpisodeSpec,
    InspectionZone,
    Pose,
    SceneLayout,
    Split,
    Viewpoint,
)

GENERATOR_VERSION = "gen-v1"
PILOT_NAMESPACE = "pilot"


@dataclass(frozen=True)
class GeneratorConfig:
    zone: InspectionZone = InspectionZone(cx=0.0, cy=0.0, cz=0.6, radius=0.5)
    camera: CameraModel = CameraModel()
    # candidate ring (per scene group: phase, radius and height jitter)
    n_candidates: int = 12
    ring_radius: float = 2.0
    ring_radius_jitter: float = 0.2
    ring_height: float = 1.1
    ring_height_jitter: float = 0.2
    # initial viewpoint (separate pose, not one of the candidates)
    initial_radius: float = 2.0
    initial_height: float = 1.1
    # object
    object_radius: float = 0.12
    # occluders: square pillars standing on the ground between ring and zone
    n_occluders_range: tuple[int, int] = (1, 3)
    occluder_radius_range: tuple[float, float] = (0.85, 1.3)
    occluder_width_range: tuple[float, float] = (0.4, 0.8)
    occluder_height_range: tuple[float, float] = (0.9, 1.5)
    p_block_initial: float = 0.5  # place one pillar on the initial line of sight
    occluder_jitter_m: float = 0.08
    occluder_jitter_rad: float = math.radians(5.0)
    variants_per_group: int = 4
    split_fractions: tuple[float, float, float] = (0.4, 0.2, 0.4)  # train, val, test


def stable_seed(*parts: object) -> int:
    """Deterministic 62-bit seed from a tuple of parts (no Python hash randomisation)."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big") >> 2


def _rng(*parts: object) -> np.random.Generator:
    return np.random.default_rng(stable_seed(*parts))


def split_for_group(namespace: str, scene_group: int, config: GeneratorConfig) -> Split:
    if namespace == PILOT_NAMESPACE:
        return Split.PILOT
    bucket = stable_seed("split", namespace, GENERATOR_VERSION, scene_group) % 1000
    train_end = int(round(config.split_fractions[0] * 1000))
    val_end = train_end + int(round(config.split_fractions[1] * 1000))
    if bucket < train_end:
        return Split.TRAIN
    if bucket < val_end:
        return Split.VAL
    return Split.TEST


def _ring_viewpoint(
    vid: int, zone: InspectionZone, azimuth: float, radius: float, height: float
) -> Viewpoint:
    pos = np.array(
        [zone.cx + radius * math.cos(azimuth), zone.cy + radius * math.sin(azimuth), height]
    )
    target = np.array([zone.cx, zone.cy, zone.cz])
    return Viewpoint(
        id=vid,
        pose=look_at_pose(pos, target),
        azimuth=azimuth % (2 * math.pi),
        radius=radius,
        height=height,
    )


def candidate_viewpoints(
    namespace: str, scene_group: int, config: GeneratorConfig
) -> tuple[Viewpoint, ...]:
    """Candidates depend on the inspection zone and the scene-group seed only."""
    rng = _rng("candidates", namespace, GENERATOR_VERSION, scene_group)
    step = 2 * math.pi / config.n_candidates
    phase = rng.uniform(0.0, step)
    radius = config.ring_radius + rng.uniform(-1, 1) * config.ring_radius_jitter
    height = config.ring_height + rng.uniform(-1, 1) * config.ring_height_jitter
    return tuple(
        _ring_viewpoint(i, config.zone, phase + i * step, radius, height)
        for i in range(config.n_candidates)
    )


def initial_viewpoint(namespace: str, scene_group: int, config: GeneratorConfig) -> Viewpoint:
    rng = _rng("initial", namespace, GENERATOR_VERSION, scene_group)
    azimuth = rng.uniform(0.0, 2 * math.pi)
    return _ring_viewpoint(
        INITIAL_VIEWPOINT_ID, config.zone, azimuth, config.initial_radius, config.initial_height
    )


def _base_occluders(
    namespace: str, scene_group: int, init_azimuth: float, config: GeneratorConfig
) -> list[tuple[float, float, float, float]]:
    """Per-group occluder parameters: (azimuth, radius, width, height)."""
    rng = _rng("layout", namespace, GENERATOR_VERSION, scene_group)
    lo, hi = config.n_occluders_range
    n = int(rng.integers(lo, hi + 1))
    block_initial = rng.uniform() < config.p_block_initial
    params = []
    for k in range(n):
        if k == 0 and block_initial:
            az = init_azimuth + rng.uniform(-1, 1) * math.radians(4.0)
        else:
            az = rng.uniform(0.0, 2 * math.pi)
        radius = rng.uniform(*config.occluder_radius_range)
        width = rng.uniform(*config.occluder_width_range)
        height = rng.uniform(*config.occluder_height_range)
        params.append((az, radius, width, height))
    return params


def _layout(
    namespace: str, scene_group: int, variant: int, init_azimuth: float, config: GeneratorConfig
) -> SceneLayout:
    base = _base_occluders(namespace, scene_group, init_azimuth, config)
    rng = _rng("variant", namespace, GENERATOR_VERSION, scene_group, variant)
    object_present = variant % 2 == 0
    jitter = variant >= 2
    zone = config.zone
    occluders = []
    for az, radius, width, height in base:
        if jitter:
            az = az + rng.uniform(-1, 1) * config.occluder_jitter_rad
            radius = radius + rng.uniform(-1, 1) * config.occluder_jitter_m
        occluders.append(
            Box(
                cx=zone.cx + radius * math.cos(az),
                cy=zone.cy + radius * math.sin(az),
                cz=height / 2.0,
                sx=width,
                sy=width,
                sz=height,
            )
        )
    object_pose = None
    # draw the object position from the same stream regardless of presence so the
    # occluder jitter above is identical between the present/absent pair of a group
    r_max = max(zone.radius - config.object_radius, 0.0)
    r = r_max * math.sqrt(rng.uniform())
    theta = rng.uniform(0.0, 2 * math.pi)
    if object_present:
        object_pose = Pose(
            x=zone.cx + r * math.cos(theta), y=zone.cy + r * math.sin(theta), z=zone.cz, yaw=0.0
        )
    return SceneLayout(
        object_present=object_present,
        object_pose=object_pose,
        object_radius=config.object_radius,
        occluders=tuple(occluders),
    )


def episode_id(namespace: str, scene_group: int, variant: int) -> str:
    return f"{namespace}-g{scene_group:04d}-v{variant}"


def generate_episode(
    namespace: str, scene_group: int, variant: int, config: GeneratorConfig | None = None
) -> EpisodeSpec:
    config = config or GeneratorConfig()
    init = initial_viewpoint(namespace, scene_group, config)
    return EpisodeSpec(
        episode_id=episode_id(namespace, scene_group, variant),
        namespace=namespace,
        scene_group=scene_group,
        variant=variant,
        seed=stable_seed("episode", namespace, GENERATOR_VERSION, scene_group, variant),
        split=split_for_group(namespace, scene_group, config),
        generator_version=GENERATOR_VERSION,
        zone=config.zone,
        camera=config.camera,
        initial_viewpoint=init,
        candidate_viewpoints=candidate_viewpoints(namespace, scene_group, config),
        layout=_layout(namespace, scene_group, variant, init.azimuth, config),
    )


def build_episode_set(
    namespace: str, n_groups: int, config: GeneratorConfig | None = None
) -> list[EpisodeSpec]:
    config = config or GeneratorConfig()
    return [
        generate_episode(namespace, g, v, config)
        for g in range(n_groups)
        for v in range(config.variants_per_group)
    ]
