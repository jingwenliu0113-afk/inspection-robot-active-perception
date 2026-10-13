"""B0 scenes (``gen-nav-b0``, decision 015): gen-v2 scenes a TurtleBot 4 can drive through.

Same zone, fire hydrant and pillar model as gen-v2, with three changes for a ground robot:
the candidate ring has a fixed radius (2.0 m) and camera height (1.1 m, the mast camera),
pillars keep >= 0.35 m from every camera position (robot radius ~0.175 m plus margin), and
an 8 m x 8 m enclosure gives AMCL something to localise against.

The prior facility map (``facility_map``) holds the walls, the pillars and the inspection
zone as a keep-out disk. It never contains the inspection target: the present and absent
variants of a scene group get the identical map.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from ..episodes import GeneratorConfig, generate_episode
from ..types import Box, EpisodeSpec, Split

GENERATOR_VERSION = "gen-nav-b0"
NAMESPACE = "nav-b0"  # B0 runs and decision 016 development
CONFIRM_NAMESPACE = "nav-b0c"  # decision 016 confirmation, generated after its freeze, run once
RECONFIRM_NAMESPACE = "nav-b0d"  # decision 016 appendix C: second confirmation, run once
CONFIG = GeneratorConfig(
    ring_radius=2.0,
    ring_radius_jitter=0.0,
    ring_height=1.1,
    ring_height_jitter=0.0,
    initial_radius=2.0,
    initial_height=1.1,
    occluder_ring_clearance=0.35,
)
WALL_HALF_M = 4.0  # inner faces of the enclosure at +-4 m
WALL_THICK_M = 0.1
WALL_HEIGHT_M = 2.0
MAP_RESOLUTION_M = 0.05
MAP_HALF_M = 4.5
MAST_PITCH = math.atan2(CONFIG.ring_height - CONFIG.zone.cz, CONFIG.ring_radius)


def b0_specs(
    n_groups: int = 6, variants: tuple[int, ...] = (0, 1), namespace: str = NAMESPACE
) -> list[EpisodeSpec]:
    """``variants`` 0 / 1 = object present / absent with the same pillars (gen-v2 rule)."""
    return [
        dataclasses.replace(
            generate_episode(namespace, g, v, CONFIG),
            generator_version=GENERATOR_VERSION,
            split=Split.NAV_DEV,
        )
        for g in range(n_groups)
        for v in variants
    ]


def walls() -> tuple[Box, ...]:
    c = WALL_HALF_M + WALL_THICK_M / 2
    span = 2 * WALL_HALF_M + 2 * WALL_THICK_M
    h = WALL_HEIGHT_M
    return (
        Box(cx=c, cy=0.0, cz=h / 2, sx=WALL_THICK_M, sy=span, sz=h),
        Box(cx=-c, cy=0.0, cz=h / 2, sx=WALL_THICK_M, sy=span, sz=h),
        Box(cx=0.0, cy=c, cz=h / 2, sx=span, sy=WALL_THICK_M, sz=h),
        Box(cx=0.0, cy=-c, cz=h / 2, sx=span, sy=WALL_THICK_M, sz=h),
    )


def facility_map(spec: EpisodeSpec) -> np.ndarray:
    """Occupancy grid (row 0 = smallest y), True = occupied. Never reads the object."""
    n = int(round(2 * MAP_HALF_M / MAP_RESOLUTION_M))
    c = -MAP_HALF_M + (np.arange(n) + 0.5) * MAP_RESOLUTION_M
    gx, gy = np.meshgrid(c, c, indexing="xy")  # gx[i, j] = x of column j, gy = y of row i
    occ = np.zeros((n, n), dtype=bool)
    for b in (*walls(), *spec.layout.occluders):
        occ |= (np.abs(gx - b.cx) <= b.sx / 2) & (np.abs(gy - b.cy) <= b.sy / 2)
    z = spec.zone
    occ |= np.hypot(gx - z.cx, gy - z.cy) <= z.radius  # keep-out: never drive through the zone
    return occ


def map_files(spec: EpisodeSpec, image_name: str) -> tuple[bytes, str]:
    """(PGM bytes, map_server YAML) for ``facility_map``; PGM row 0 is the top (largest y)."""
    occ = facility_map(spec)[::-1]
    pixels = np.where(occ, 0, 254).astype(np.uint8)
    h, w = pixels.shape
    pgm = f"P5\n{w} {h}\n255\n".encode() + pixels.tobytes()
    yaml = (
        f"image: {image_name}\nmode: trinary\nresolution: {MAP_RESOLUTION_M}\n"
        f"origin: [{-MAP_HALF_M}, {-MAP_HALF_M}, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.25\n"
    )
    return pgm, yaml


def specs_by_id() -> dict[str, EpisodeSpec]:
    namespaces = (NAMESPACE, CONFIRM_NAMESPACE, RECONFIRM_NAMESPACE)
    return {s.episode_id: s for ns in namespaces for s in b0_specs(namespace=ns)}
