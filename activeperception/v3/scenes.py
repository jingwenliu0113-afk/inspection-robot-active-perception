"""v3 development scenes with a distractor (decision 024): gen-nav-v1 plus one more fire hydrant
outside the inspection zone, so that "is the detection in the zone?" matters.

    uv run python -m activeperception.v3.scenes --namespace v3-dev-dx --groups 30 \\
        --out data/episodes/specs-v3-dev-dx.json

Each scene group gets one distractor (the same for all its variants), either "near" (between
the zone and the viewpoint ring) or "far" (behind the ring, in the background of views across
the zone). It keeps clear of the pillars, the zone, every viewpoint and the walls. Development
only: these scenes are never a formal evaluation set.
"""

from __future__ import annotations

import argparse
import dataclasses
import math

import numpy as np

from ..nav import scene
from ..serialize import save_spec_set
from ..types import Pose, Split

GENERATOR_VERSION = "gen-nav-v1+dx-dev"
NEAR_R = (0.95, 1.45)  # from the zone centre (zone radius 0.5; viewpoint ring 2.0)
FAR_R = (2.45, 3.3)
CLEAR_PILLAR_M = 0.45
CLEAR_VIEWPOINT_M = 0.45
WALL_LIMIT_M = scene.WALL_HALF_M - 0.4


def _ok(x: float, y: float, spec) -> bool:
    if max(abs(x), abs(y)) > WALL_LIMIT_M:
        return False
    for b in spec.layout.occluders:
        dx = max(abs(x - b.cx) - b.sx / 2, 0.0)
        dy = max(abs(y - b.cy) - b.sy / 2, 0.0)
        if math.hypot(dx, dy) < CLEAR_PILLAR_M:
            return False
    vps = (spec.initial_viewpoint, *spec.candidate_viewpoints)
    return all(math.hypot(x - v.pose.x, y - v.pose.y) >= CLEAR_VIEWPOINT_M for v in vps)


def place_distractor(spec, rng: np.random.Generator) -> Pose:
    z = spec.zone
    for _ in range(1000):
        lo, hi = NEAR_R if rng.random() < 0.5 else FAR_R
        r, a = rng.uniform(lo, hi), rng.uniform(0, 2 * math.pi)
        x, y = z.cx + r * math.cos(a), z.cy + r * math.sin(a)
        if _ok(x, y, spec):
            return Pose(x, y, 0.0, rng.uniform(0, 2 * math.pi), 0.0)
    raise RuntimeError(f"{spec.episode_id}: no place for a distractor")


def distractor_specs(namespace: str, n_groups: int) -> list:
    base = scene.nav_specs(namespace, n_groups)
    out, placed = [], {}
    for s in base:
        if s.scene_group not in placed:
            placed[s.scene_group] = place_distractor(
                s, np.random.default_rng([20261015, s.scene_group])
            )
        lay = dataclasses.replace(s.layout, distractors=(placed[s.scene_group],))
        out.append(
            dataclasses.replace(
                s, layout=lay, generator_version=GENERATOR_VERSION, split=Split.R0_DEV
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v3.scenes")
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--groups", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    specs = distractor_specs(args.namespace, args.groups)
    save_spec_set(args.out, specs, extra={"namespace": args.namespace})
    print(f"wrote {len(specs)} {GENERATOR_VERSION} specs -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
