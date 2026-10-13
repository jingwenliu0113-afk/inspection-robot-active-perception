"""B1 closed-loop run (decision 017). Runs INSIDE the ``inspection-ap-navdet`` container.

    python3 -m activeperception.nav.b1_driver prepare --specs S --episode E --out OUT
    python3 -m activeperception.nav.b1_driver run --specs S --episodes-gt G --renders R \\
        --teleport-detections T --episode E --method rule --seed 0 --budget 5 --out OUT

One (episode, method, seed) per container. From the initial viewpoint: capture -> detector
-> decision-016 observation -> frozen ``decision-v2``; while ``inconclusive`` and under the
budget, the policy picks the next candidate, Nav2 drives there, the stop is relocalised
(``nav-relocalize-v1``) and captured. The policies never read the remaining budget, so one
budget-5 run gives the budget 1-5 outcomes as prefixes.

Deployable path: the AMCL estimate, onboard frames, detector, facility map. Ground truth
(``/gt/odom``, labels) is written to the ``scoring`` fields only. The oracle is the usual
non-deployable upper bound (GT state + teleport observations of the candidates).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .. import frozen_v2
from ..types import Decision, EpisodeSpec
from .b0_driver import Driver, prepare

METHODS = ("single", "random", "rule", "oracle")


def make_policy(method: str, args, spec: EpisodeSpec):
    from ..policies import OracleNBVv2Policy, RandomNBVPolicy, SingleViewPolicy

    if method == "single":
        return SingleViewPolicy()
    if method == "random":
        return RandomNBVPolicy()
    if method == "rule":
        return frozen_v2.rule_nbv()
    if method == "oracle":  # upper bound, not deployable
        from ..detector.cache import DetectionCache
        from ..framestore import FrameStore
        from ..serialize import load_episode_set
        from ..sim.replay import GazeboReplayWorld, make_peek

        specs, gts, _ = load_episode_set(args.episodes_gt)
        world = GazeboReplayWorld(
            FrameStore(args.renders), DetectionCache.load(args.teleport_detections)
        )
        return OracleNBVv2Policy(gts.__getitem__, make_peek(world, specs), frozen_v2.DECISION_V2)
    raise ValueError(method)


class ClosedLoop(Driver):
    def __init__(self, spec: EpisodeSpec, out: Path, policy, detector):
        super().__init__(spec, out, relocalize=True)
        self.policy = policy
        self.detector = detector
        self.rule = frozen_v2.decision_rule()

    def observe(self, row: dict, viewpoint_id: int):
        from ..detector.cache import make_detection
        from ..framestore import decode_depth_mm, encode_depth_mm
        from .observe import deployable_camera_pose, observation_d016

        rgb = self.last_frames["rgb"].array
        depth = decode_depth_mm(encode_depth_mm(self.last_frames["depth"].array))
        h, w = depth.shape
        dets = tuple(make_detection(d[0], d[1:5], w, h) for d in self.detector.detect(rgb))
        pose = deployable_camera_pose(row["deployable"]["estimate"])
        obs, ref = observation_d016(self.spec, viewpoint_id, depth, dets, pose)
        info = {
            "refine_ok": ref.ok,
            "refined_pose": [obs.viewpoint.pose.x, obs.viewpoint.pose.y, obs.viewpoint.pose.yaw],
            "max_conf": obs.max_confidence,
            "detections": [[d.confidence, *d.bbox] for d in dets],
        }
        return obs, info

    def run_loop(self, budget: int, seed: int) -> dict:
        episode = self.spec.deployable()
        p = self.spec.initial_viewpoint.pose
        w0 = time.monotonic()
        self.start(p.x, p.y, p.yaw)
        self.policy.reset(episode, seed)
        row = {"step": None, "nav": None, **self.capture("initial", -1)}
        obs, info = self.observe(row, -1)
        history = [obs]
        out = self.rule.decide(episode, history)
        steps = [self._step(row, info, out, history)]
        self._log(row)
        while out.decision == Decision.INCONCLUSIVE and len(history) < budget:
            nxt = self.policy.select_next(episode, tuple(history), budget - len(history))
            if nxt is None:
                break
            step = {"kind": "goal", "target": int(nxt)}
            nav = self.navigate(step)
            row = {"step": step, "nav": nav, **self.capture("goal", int(nxt))}
            obs, info = self.observe(row, int(nxt))
            history.append(obs)
            out = self.rule.decide(episode, history)
            steps.append(self._step(row, info, out, history))
            self._log(row)
        return {
            "episode_id": self.spec.episode_id,
            "budget": budget,
            "seed": seed,
            "policy": self.policy.name,
            "final_decision": out.decision.value,
            "total_wall_s": round(time.monotonic() - w0, 1),
            "steps": steps,
        }

    def _step(self, row, info, out, history) -> dict:
        return {
            **row,
            "observation": info,
            "decision": out.decision.value,
            "confidence": out.confidence,
            "cleared_fraction": self.rule.cleared_fraction(history),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.nav.b1_driver")
    ap.add_argument("action", choices=["prepare", "run"])
    ap.add_argument("--specs", required=True)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--episodes-gt")
    ap.add_argument("--renders")
    ap.add_argument("--teleport-detections")
    ap.add_argument("--method", choices=METHODS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=int, default=5)
    args = ap.parse_args(argv)
    from ..serialize import load_spec_set

    spec = {s.episode_id: s for s in load_spec_set(args.specs)[0]}[args.episode]
    if args.action == "prepare":
        prepare(spec, Path(args.out) / spec.episode_id)
        return 0
    import rclpy

    from ..detector import FROZEN_DETECTOR
    from ..detector.models import load_detector

    run_dir = Path(args.out) / spec.episode_id / f"{args.method}-s{args.seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    detector = load_detector(FROZEN_DETECTOR, "models", "cpu")
    rclpy.init()
    loop = ClosedLoop(spec, run_dir, make_policy(args.method, args, spec), detector)
    report = loop.run_loop(args.budget, args.seed)
    report["method"] = args.method
    (run_dir / "run.json").write_text(json.dumps(report, indent=1))
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
