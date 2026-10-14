"""R0b (decision 022): v2 safety under modelled depth noise and pose error. Simulation only.

    uv run python -m activeperception.r0b --ns r0b-dev --out runs/r0b-dev/analysis   # dev
    uv run python -m activeperception.r0b --ns r0b --out results/r0b                 # formal, once

Inputs: ``data/episodes/gazebo-<ns>.json``, ``renders/<ns>`` (teleport render) and
``runs/<ns>/detector-v1.jsonl`` (frozen detector on the clean RGB). Each condition replays
the four methods through the Core harness on a ``NoisyWorld``: the depth of every view gets
the modelled sensor error and the camera pose the robot believes in gets the modelled
localisation / calibration error; pipeline (a) uses that estimate directly, pipeline (b) is
decision 016 (map refinement on the noisy depth + pose margin). Ground truth (object
position, states) is used for scoring only.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import frozen_v2
from .r0b_noise import DepthNoise, PoseNoise, apply_depth_noise, perturb_pose, rng_for
from .sensing import cleared_locations, location_grid
from .types import Observation

DEPTH_LEVELS: dict[str, DepthNoise | None] = {
    "D0": None,
    "D1": DepthNoise(
        "D1", rel_at_2m=0.01, bias=0.01, corr_px=3.0, edge_px=2, edge_jump_m=0.10, dropout=0.01
    ),
    "D2": DepthNoise(
        "D2", rel_at_2m=0.02, bias=0.02, corr_px=3.0, edge_px=3, edge_jump_m=0.10, dropout=0.03
    ),
}
POSE_LEVELS: dict[str, PoseNoise | None] = {
    "P0": None,
    "L1": PoseNoise("L1", sigma_xy=0.03, sigma_yaw=0.02, sigma_z=0.01, sigma_pitch=0.005),
    "L2": PoseNoise("L2", sigma_xy=0.06, sigma_yaw=0.04, sigma_z=0.02, sigma_pitch=0.010),
}
PIPELINES = ("a", "b")
OCCUPIED_RADIUS_M = 0.06  # inside the hydrant body (decision 022 appendix A; 0.10 m was too wide)
PRIMARY = ("D1", "L1", "b")  # R1
STRESS = ("D2", "L2", "b")  # R2
EVAL_NAMESPACES = ("r0b",)


def conditions() -> list[tuple[str, str, str]]:
    return list(itertools.product(DEPTH_LEVELS, POSE_LEVELS, PIPELINES))


def occupied_locations(spec) -> np.ndarray:
    """Scoring only: candidate locations inside the object's footprint (none if absent)."""
    grid = location_grid(spec.zone)
    if not spec.layout.object_present:
        return np.zeros(len(grid), dtype=bool)
    o = spec.layout.object_pose
    return np.hypot(grid[:, 0] - o.x, grid[:, 1] - o.y) <= OCCUPIED_RADIUS_M


class NoisyWorld:
    """Replay world whose observations carry the modelled depth and pose errors."""

    name = "gazebo-r0b"

    def __init__(self, base, depth_level: str, pose_level: str, pipeline: str):
        self.base = base
        self.depth_level, self.pose_level, self.pipeline = depth_level, pose_level, pipeline
        self._cache: dict[tuple[str, int], Observation] = {}
        self.diag: dict[tuple[str, int], dict] = {}

    def observe(self, spec, viewpoint) -> Observation:
        from .nav.observe import observation, observation_d016

        key = (spec.episode_id, viewpoint.id)
        if key in self._cache:
            return self._cache[key]
        self.base.zone_visible_fraction(spec, viewpoint)  # spec digest + rendered pose checks
        depth = self.base._frames(spec).depth(viewpoint.id)
        view = f"v{viewpoint.id}"
        dn = DEPTH_LEVELS[self.depth_level]
        if dn is not None:
            depth = apply_depth_noise(depth, dn, rng_for(spec.episode_id, view, "depth", dn.name))
        estimate = viewpoint.pose
        pn = POSE_LEVELS[self.pose_level]
        if pn is not None:
            estimate = perturb_pose(
                viewpoint.pose, pn, rng_for(spec.episode_id, view, "pose", pn.name)
            )
        dets = self.base.detections.get(spec.episode_id, viewpoint.id)
        ref = None
        if self.pipeline == "a":
            obs = observation(spec, viewpoint.id, depth, dets, estimate)
        else:
            obs, ref = observation_d016(spec, viewpoint.id, depth, dets, estimate)
        used, true = obs.viewpoint.pose, viewpoint.pose
        seen = np.asarray(obs.location_visibility) >= frozen_v2.DECISION_V2.col_min - 1e-9
        self.diag[key] = {  # scoring only
            "occupied_cleared": bool((seen & occupied_locations(spec)).any()),
            "pose_err_xy": math.hypot(used.x - true.x, used.y - true.y),
            "pose_err_yaw": abs((used.yaw - true.yaw + math.pi) % (2 * math.pi) - math.pi),
            "refine_ok": None if ref is None else bool(ref.ok),
        }
        self._cache[key] = obs
        return obs


def run_condition(args: tuple) -> dict:
    ns, depth_level, pose_level, pipeline = args
    from .detector.cache import DetectionCache
    from .framestore import FrameStore
    from .nav.b1_analysis import summarize, teleport_outcomes
    from .serialize import load_episode_set
    from .sim.replay import GazeboReplayWorld

    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    base = GazeboReplayWorld(
        FrameStore(f"renders/{ns}"), DetectionCache.load(f"runs/{ns}/detector-v1.jsonl")
    )
    world = NoisyWorld(base, depth_level, pose_level, pipeline)
    outcomes = teleport_outcomes(specs, gts, world)
    rule = frozen_v2.decision_rule()
    all_views_risk = []
    for s in specs:
        hist = [world.observe(s, vp) for vp in (s.initial_viewpoint, *s.candidate_viewpoints)]
        if s.layout.object_present and cleared_locations(hist, rule.params.col_min).all():
            all_views_risk.append(s.episode_id)
    d = list(world.diag.values())
    present = [v for (e, _), v in world.diag.items() if gts[e].object_present]
    ref = [v["refine_ok"] for v in d if v["refine_ok"] is not None]
    return {
        "condition": {"depth": depth_level, "pose": pose_level, "pipeline": pipeline},
        "summary": summarize(outcomes, specs, gts),
        "all_views_geometric_risk": all_views_risk,
        "occupied_false_clearance": {
            "views": sum(v["occupied_cleared"] for v in present),
            "present_views": len(present),
        },
        "pose_error_used": {
            "xy_p50": float(np.median([v["pose_err_xy"] for v in d])),
            "xy_p95": float(np.quantile([v["pose_err_xy"] for v in d], 0.95)),
            "yaw_p95": float(np.quantile([v["pose_err_yaw"] for v in d], 0.95)),
        },
        "refine_ok_rate": float(np.mean(ref)) if ref else None,
    }


def safe(res: dict) -> bool:
    s = res["summary"]
    return (
        all(v["false_absent"] == 0 and v["geometric_risk"] == 0 for v in s.values())
        and not res["all_views_geometric_risk"]
    )


def criteria(results: list[dict]) -> dict:
    by = {tuple(r["condition"].values()): r for r in results}

    def grid(pipeline: str) -> dict:
        return {f"{d}x{p}": safe(by[(d, p, pipeline)]) for d in DEPTH_LEVELS for p in POSE_LEVELS}

    return {
        "R1_primary_D1_L1_b": {"pass": safe(by[PRIMARY])},
        "R2_stress_D2_L2_b": {"pass": safe(by[STRESS])},
        "R3_pipeline_a_safe": grid("a"),
        "pipeline_b_safe": grid("b"),
    }


LEGEND = (
    "FA = false absent（四個方法、budget 1–5 合計）；GR = 策略所選視角的 geometric risk；"
    "全視角 = 13 個視角聯集後仍全部看穿的物件存在 episode 數；"
    "佔用看穿 = 物件中心 0.06 m 內的位置被判為看穿的視角數 / 物件存在的視角數。"
)


def _cell(r: dict) -> str:
    sm, occ = r["summary"], r["occupied_false_clearance"]
    fa = sum(v["false_absent"] for v in sm.values())
    gr = sum(v["geometric_risk"] for v in sm.values())
    av = len(r["all_views_geometric_risk"])
    mark = "安全" if safe(r) else "**不安全**"
    return (
        f"{mark}：FA {fa}、GR {gr}、全視角 {av}；佔用看穿 {occ['views']}/{occ['present_views']}；"
        f"Rule b2 {sm['rule@2']['accuracy']:.3f}"
    )


def markdown(report: dict) -> str:
    """Grids for results/r0b/README.md: depth level x pose level, one per pipeline."""
    by = {tuple(r["condition"].values()): r for r in report["results"]}
    names = {"a": "(a) v2 直接用估計位姿", "b": "(b) v2 + decision 016（精修 + 餘裕）"}
    out = []
    for pipe in PIPELINES:
        head = "| depth \\ 位姿 | " + " | ".join(POSE_LEVELS) + " |"
        out += [f"### {names[pipe]}", "", head, "|---|" + "---|" * len(POSE_LEVELS)]
        for d in DEPTH_LEVELS:
            out.append(
                f"| {d} | " + " | ".join(_cell(by[(d, p, pipe)]) for p in POSE_LEVELS) + " |"
            )
        out.append("")
    c = report["criteria"]
    r1 = "**通過**" if c["R1_primary_D1_L1_b"]["pass"] else "**未通過**"
    r2 = "通過" if c["R2_stress_D2_L2_b"]["pass"] else "**未通過**"
    out += [
        LEGEND,
        "",
        "### 判準（decision 022 §6）",
        "",
        f"- R1（主要，管線 b、D1 × L1）：{r1}",
        f"- R2（壓力，管線 b、D2 × L2）：{r2}",
        "",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.r0b")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=9)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if args.ns in EVAL_NAMESPACES and (out / "report.json").exists():
        sys.exit(f"{out}/report.json exists: the formal R0b run is done once (decision 022)")
    jobs = [(args.ns, *c) for c in conditions()]
    with ProcessPoolExecutor(args.workers) as ex:
        results = list(ex.map(run_condition, jobs))
    report = {"namespace": args.ns, "results": results, "criteria": criteria(results)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    (out / "tables.md").write_text(markdown(report))
    for r in results:
        c = r["condition"]
        rule2, occ = r["summary"]["rule@2"], r["occupied_false_clearance"]
        print(
            f"{c['depth']} {c['pose']} {c['pipeline']}: safe={safe(r)} "
            f"all-views-risk={len(r['all_views_geometric_risk'])} "
            f"occupied={occ['views']}/{occ['present_views']} "
            f"rule@2 acc={rule2['accuracy']:.3f} refine_ok={r['refine_ok_rate']}"
        )
    print(json.dumps(report["criteria"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
