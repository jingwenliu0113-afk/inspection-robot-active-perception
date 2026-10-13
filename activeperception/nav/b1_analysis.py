"""B1 / B2 analysis (decision 017): Nav2 closed loop vs the teleport reference, same episodes.

    uv run python -m activeperception.nav.b1_analysis --ns nav-b1 --out results/nav-b1

- teleport: the four methods replayed on the teleport render of the same scenes (Core
  harness, frozen v2, exact poses).
- nav2: ``runs/<ns>/<episode>/<method>-s<seed>/run.json``; the budget-b outcome is the
  decision after min(b, views taken) views (the runs stop at a definitive answer).
Ground truth (episode state, object presence, ``/gt/odom`` traces) is used for scoring only.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .. import frozen_v2
from ..detector.cache import DetectionCache
from ..framestore import FrameStore
from ..grader import grade
from ..harness import run_episode
from ..policies import OracleNBVv2Policy, RandomNBVPolicy, SingleViewPolicy
from ..serialize import load_episode_set
from ..sim.replay import GazeboReplayWorld, make_peek
from .b0_analysis import ARRIVAL_XY_M, ARRIVAL_YAW, _angle, clearance

BUDGETS = (1, 2, 3, 4, 5)
RANDOM_SEEDS = (0, 1, 2)
JOBS = (("single", 0), ("rule", 0), ("oracle", 0), *(("random", s) for s in RANDOM_SEEDS))


def _outcome(decision: str, present: bool, cleared: float, views: int) -> dict:
    expected = "present" if present else "absent"
    return {
        "correct": decision == expected,
        "decision": decision,
        "inconclusive": decision == "inconclusive",
        "false_absent": present and decision == "absent",
        "false_present": (not present) and decision == "present",
        "geometric_risk": present and cleared >= 1.0 - 1e-9,
        "views": views,
    }


def teleport_outcomes(specs, gts, world) -> dict:
    rule = frozen_v2.decision_rule()
    peek = make_peek(world, specs)
    out: dict = {}
    for method, seed in JOBS:
        for b in BUDGETS:
            if method == "single":
                pol = SingleViewPolicy()
            elif method == "random":
                pol = RandomNBVPolicy()
            elif method == "rule":
                pol = frozen_v2.rule_nbv()
            else:
                pol = OracleNBVv2Policy(gts.__getitem__, peek, frozen_v2.DECISION_V2)
            for s in specs:
                rec = run_episode(s, world, pol, rule, b, seed)
                o = grade(rec, gts[s.episode_id], s)
                hist = [world.observe(s, s.initial_viewpoint)] + [
                    world.observe(s, s.deployable().candidate(v))
                    for v in rec.viewpoint_sequence[1:]
                ]
                out[(method, seed, b, s.episode_id)] = _outcome(
                    o.decision,
                    s.layout.object_present,
                    rule.cleared_fraction(hist),
                    o.viewpoints_used,
                )
    return out


def nav_outcomes(runs: Path, specs) -> tuple[dict, list[dict], list[dict]]:
    out, navs, missing = {}, [], []
    for s in specs:
        for method, seed in JOBS:
            p = runs / s.episode_id / f"{method}-s{seed}" / "run.json"
            if not p.exists():
                missing.append({"episode": s.episode_id, "job": f"{method}-s{seed}"})
                continue
            run = json.loads(p.read_text())
            steps = run["steps"]
            for b in BUDGETS:
                st = steps[min(b, len(steps)) - 1]
                out[(method, seed, b, s.episode_id)] = _outcome(
                    st["decision"],
                    s.layout.object_present,
                    st["cleared_fraction"],
                    min(b, len(steps)),
                )
            for st in steps[1:]:
                nav, gt = st["nav"], st["scoring"]["gt_base"]
                g = nav["goal"]
                trace = np.load(p.parent / nav["trace_file"])
                xy = trace[:, 1:3] if len(trace) else np.zeros((0, 2))
                rl = nav.get("relocalize") or {"corrections": 0, "steps": []}
                navs.append(
                    {
                        "episode": s.episode_id,
                        "method": method,
                        "seed": seed,
                        "result": nav["result"],
                        "timed_out": nav["timed_out"] or nav["wall_timeout"],
                        "arrival_xy_m": math.hypot(gt["x"] - g["x"], gt["y"] - g["y"]),
                        "arrival_yaw": _angle(gt["yaw"] - g["yaw"]),
                        "sim_s": nav["sim_s"],
                        "path_m": float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum()),
                        "clearance": clearance(trace, s),
                        "corrections": rl["corrections"],
                        "refine_ok": st["observation"]["refine_ok"],
                    }
                )
    return out, navs, missing


def summarize(outcomes: dict, specs, gts) -> dict:
    state = {s.episode_id: gts[s.episode_id].state.value for s in specs}
    res: dict = {}
    for method in ("single", "random", "rule", "oracle"):
        seeds = RANDOM_SEEDS if method == "random" else (0,)
        for b in BUDGETS:
            rows = [
                (s.episode_id, outcomes[(method, sd, b, s.episode_id)])
                for s in specs
                for sd in seeds
                if (method, sd, b, s.episode_id) in outcomes
            ]
            if not rows:
                continue
            present = [o for e, o in rows if state[e] != "absent"]
            absent = [o for e, o in rows if state[e] == "absent"]
            by_state = defaultdict(list)
            for e, o in rows:
                by_state[state[e]].append(o["correct"])
            res[f"{method}@{b}"] = {
                "n": len(rows),
                "accuracy": float(np.mean([o["correct"] for _, o in rows])),
                "inconclusive_rate": float(np.mean([o["inconclusive"] for _, o in rows])),
                "false_absent": sum(o["false_absent"] for o in present),
                "false_present": sum(o["false_present"] for o in absent),
                "geometric_risk": sum(o["geometric_risk"] for _, o in rows),
                "avg_views": float(np.mean([o["views"] for _, o in rows])),
                "accuracy_by_state": {k: float(np.mean(v)) for k, v in sorted(by_state.items())},
            }
    return res


def paired(nav: dict, tel: dict) -> dict:
    out = {}
    for method in ("single", "random", "rule", "oracle"):
        for b in BUDGETS:
            keys = [k for k in nav if k[0] == method and k[2] == b and k in tel]
            if not keys:
                continue
            d = [nav[k]["correct"] - tel[k]["correct"] for k in keys]
            out[f"{method}@{b}"] = {
                "n": len(keys),
                "nav_minus_teleport_accuracy": float(np.mean(d)),
                "nav_only_correct": int(sum(x > 0 for x in d)),
                "teleport_only_correct": int(sum(x < 0 for x in d)),
            }
    return out


def nav_metrics(navs: list[dict]) -> dict:
    def q(v, p):
        return float(np.quantile(v, p)) if v else None

    ok = [
        n
        for n in navs
        if n["result"] == "SUCCEEDED"
        and n["arrival_xy_m"] <= ARRIVAL_XY_M
        and n["arrival_yaw"] <= ARRIVAL_YAW
    ]
    by_method = defaultdict(list)
    for n in navs:
        by_method[n["method"]].append(n["path_m"])
    return {
        "navigations": len(navs),
        "path_success_rate": len(ok) / len(navs) if navs else None,
        "nav2_reported_success": sum(n["result"] == "SUCCEEDED" for n in navs),
        "timeouts": sum(n["timed_out"] for n in navs),
        "collisions": sum((n["clearance"]["obstacle_m"] or 0) < 0 for n in navs),
        "zone_entries": sum((n["clearance"]["zone_m"] or 0) < 0 for n in navs),
        "latency_sim_s_p50": q([n["sim_s"] for n in navs], 0.5),
        "latency_sim_s_p95": q([n["sim_s"] for n in navs], 0.95),
        "path_m_per_navigation_p50": q([n["path_m"] for n in navs], 0.5),
        "path_m_per_navigation_by_method": {
            k: float(np.mean(v)) for k, v in sorted(by_method.items())
        },
        "relocalize_corrections": {
            str(k): sum(n["corrections"] == k for n in navs) for k in range(3)
        },
        "refine_failed": sum(not n["refine_ok"] for n in navs),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.nav.b1_analysis")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    ns = args.ns
    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    world = GazeboReplayWorld(
        FrameStore(f"renders/{ns}"), DetectionCache.load(f"runs/{ns}/teleport-detector-v1.jsonl")
    )
    tel = teleport_outcomes(specs, gts, world)
    nav, navs, missing = nav_outcomes(Path("runs") / ns, specs)
    report = {
        "namespace": ns,
        "episodes": len(specs),
        "states": {
            k: sum(gts[s.episode_id].state.value == k for s in specs)
            for k in ("visible", "unobservable", "absent")
        },
        "missing_runs": missing,
        "teleport": summarize(tel, specs, gts),
        "nav2": summarize(nav, specs, gts),
        "nav2_minus_teleport": paired(nav, tel),
        "navigation": nav_metrics(navs),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "b1_report.json").write_text(json.dumps(report, indent=1) + "\n")
    for b in (1, 2, 3, 5):
        line = []
        for m in ("single", "random", "rule", "oracle"):
            t, n = report["teleport"].get(f"{m}@{b}"), report["nav2"].get(f"{m}@{b}")
            if t and n:
                line.append(f"{m} tel {t['accuracy']:.3f} nav {n['accuracy']:.3f}")
        print(f"budget {b}: " + " | ".join(line))
    print(json.dumps(report["navigation"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
