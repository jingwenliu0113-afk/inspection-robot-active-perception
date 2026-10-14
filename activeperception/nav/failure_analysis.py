"""Advanced B failure analysis (portfolio wrap-up, after decision 019). Post hoc and read-only.

    uv run python -m activeperception.nav.failure_analysis --out results/nav-failure-analysis

Reads the committed B0 reports (``results/nav-b0*/b0_report.json``) and the local ``nav-b2``
run logs (``runs/nav-b2``, the same files ``b1_analysis`` scored). Nothing is rerun, no
frozen value changes, and ``nav-b2`` stays used up: this only explains the committed
numbers. Ground truth (states, ``/gt/odom`` poses, per-viewpoint visibility) is read here
for scoring and explanation only, as everywhere else.

1. ``discordant``: every (method, seed, budget) where teleport and Nav2 disagree on
   correctness at the formal budgets, step by step (same viewpoints? cleared fraction,
   max confidence, arrival error).
2. ``relocalization`` / ``capture_refinement``: how ``nav-relocalize-v1`` ended (corrections
   used, final refined error vs the 0.07 m / 0.05 rad tolerance, time) and where the
   capture-time pose refinement fell back to the wide margin.
3. ``attempts``: start-up watchdog retries in the batch log.
4. ``b0_lineage``: the B0 -> nav-b0c -> nav-b0d criteria side by side (committed reports).
5. ``cost_per_episode``: per-episode path length / navigation time, Rule vs Random.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from .b0_driver import MAX_CORRECTIONS, XY_GOAL_TOLERANCE, YAW_GOAL_TOLERANCE
from .b1_analysis import FORMAL_BUDGETS, JOBS, RANDOM_SEEDS

B0_NAMESPACES = ("nav-b0", "nav-b0c", "nav-b0d")


def _q(values, p):
    return float(np.quantile(values, p)) if len(values) else None


def nav_steps(run: dict) -> list[dict]:
    """Per view of a closed-loop run: target, decision input summary and (scoring) arrival."""
    out = []
    for st in run["steps"]:
        row = {
            "target": st["target"],
            "decision": st["decision"],
            "cleared_fraction": st["cleared_fraction"],
            "max_conf": st["observation"]["max_conf"],
            "refine_ok": st["observation"]["refine_ok"],
        }
        nav = st.get("nav")
        if nav:
            g, gt = nav["goal"], st["scoring"]["gt_base"]
            row["arrival_xy_m"] = math.hypot(gt["x"] - g["x"], gt["y"] - g["y"])
            row["arrival_yaw"] = abs((gt["yaw"] - g["yaw"] + math.pi) % (2 * math.pi) - math.pi)
        out.append(row)
    return out


def teleport_steps(spec, world, method: str, seed: int, budget: int, gts) -> list[dict]:
    """Same episode on the teleport reference (Core harness, frozen v2, exact poses)."""
    from .. import frozen_v2
    from ..harness import run_episode
    from ..policies import OracleNBVv2Policy, RandomNBVPolicy, SingleViewPolicy
    from ..sim.replay import make_peek

    rule = frozen_v2.decision_rule()
    if method == "single":
        pol = SingleViewPolicy()
    elif method == "random":
        pol = RandomNBVPolicy()
    elif method == "rule":
        pol = frozen_v2.rule_nbv()
    else:
        pol = OracleNBVv2Policy(gts.__getitem__, make_peek(world, [spec]), frozen_v2.DECISION_V2)
    rec = run_episode(spec, world, pol, rule, budget, seed)
    ep = spec.deployable()
    hist, out = [], []
    for k, v in enumerate(rec.viewpoint_sequence):
        vp = spec.initial_viewpoint if k == 0 else ep.candidate(v)
        hist.append(world.observe(spec, vp))
        d = rule.decide(ep, hist)
        out.append(
            {
                "target": -1 if k == 0 else int(v),
                "decision": d.decision.value,
                "cleared_fraction": rule.cleared_fraction(hist),
                "max_conf": max(o.max_confidence for o in hist),
            }
        )
    return out


def explain(tel: list[dict], nav: list[dict], present: bool) -> str:
    """One-line cause for a teleport / Nav2 disagreement (same final view count assumed)."""
    same_views = [t["target"] for t in tel] == [n["target"] for n in nav[: len(tel)]]
    t, n = tel[-1], nav[min(len(tel), len(nav)) - 1]
    if not same_views:
        return "different viewpoints chosen"
    if present:
        return (
            f"same viewpoints; detection at the stop {n['max_conf']:.2f} vs teleport "
            f"{t['max_conf']:.2f} (present needs >= 0.7)"
        )
    return (
        f"same viewpoints; seen-through locations {n['cleared_fraction']:.3f} (Nav2, with pose "
        f"margin) vs {t['cleared_fraction']:.3f} (teleport); absent needs 1.0"
    )


def discordant(nav_out: dict, tel_out: dict, specs, gts, world, runs: Path, budgets) -> list:
    by_id = {s.episode_id: s for s in specs}
    rows = []
    for key in sorted(nav_out):
        method, seed, b, eid = key
        if b not in budgets or key not in tel_out:
            continue
        if nav_out[key]["correct"] == tel_out[key]["correct"]:
            continue
        spec, gt = by_id[eid], gts[eid]
        run = json.loads((runs / eid / f"{method}-s{seed}" / "run.json").read_text())
        nav = nav_steps(run)[:b]
        tel = teleport_steps(spec, world, method, seed, b, gts)
        rows.append(
            {
                "method": method,
                "seed": seed,
                "budget": b,
                "episode": eid,
                "state": gt.state.value,
                "teleport": tel_out[key]["decision"],
                "nav2": nav_out[key]["decision"],
                "nav2_correct": nav_out[key]["correct"],
                "teleport_steps": tel,
                "nav2_steps": nav,
                "gt_visibility_of_views": [
                    gt.visibility_initial
                    if s["target"] < 0
                    else gt.visibility_by_viewpoint[s["target"]]
                    for s in nav
                ],
                "cause": explain(tel, nav, spec.layout.object_present),
            }
        )
    return rows


def capture_refinement(runs: Path, specs) -> dict:
    """Capture-time ``nav-pose-v1`` failures (the decision then uses the wide fallback margin)."""
    failed: dict[str, list] = {"initial": [], "goal": []}
    n = Counter()
    for s in specs:
        for method, seed in JOBS:
            run = json.loads((runs / s.episode_id / f"{method}-s{seed}" / "run.json").read_text())
            for i, st in enumerate(run["steps"]):
                tag = "initial" if i == 0 else "goal"
                n[tag] += 1
                if not st["observation"]["refine_ok"]:
                    failed[tag].append(
                        {"episode": s.episode_id, "job": f"{method}-s{seed}", "view": i}
                    )
    return {
        "captures": dict(n),
        "failed": {k: len(v) for k, v in failed.items()},
        "initial_failed_scene_groups": sorted(
            {f["episode"].rsplit("-", 1)[0] for f in failed["initial"]}
        ),
        "goal_failed": failed["goal"],
    }


def relocalization(runs: Path, specs) -> dict:
    final_xy, final_yaw, within, by_corr = [], [], 0, Counter()
    sim_by_corr: dict[int, list[float]] = {k: [] for k in range(MAX_CORRECTIONS + 1)}
    refine_failed = []
    n = 0
    for s in specs:
        for method, seed in JOBS:
            run = json.loads((runs / s.episode_id / f"{method}-s{seed}" / "run.json").read_text())
            for i, st in enumerate(run["steps"][1:], start=1):
                rl = st["nav"]["relocalize"]
                n += 1
                by_corr[rl["corrections"]] += 1
                sim_by_corr[rl["corrections"]].append(st["nav"]["sim_s"])
                last = rl["steps"][-1]
                if not last["refine_ok"]:
                    refine_failed.append(
                        {
                            "episode": s.episode_id,
                            "job": f"{method}-s{seed}",
                            "view": i,
                            "decision_after_view": st["decision"],
                        }
                    )
                    continue
                final_xy.append(last["err_xy"])
                final_yaw.append(last["err_yaw"])
                within += (
                    last["err_xy"] <= XY_GOAL_TOLERANCE and last["err_yaw"] <= YAW_GOAL_TOLERANCE
                )
    return {
        "navigations": n,
        "corrections_used": {str(k): by_corr[k] for k in range(MAX_CORRECTIONS + 1)},
        "max_corrections": MAX_CORRECTIONS,
        "tolerance": {"xy_m": XY_GOAL_TOLERANCE, "yaw": YAW_GOAL_TOLERANCE},
        "final_refined_error": {
            "n": len(final_xy),
            "within_tolerance": int(within),
            "xy_p50_m": _q(final_xy, 0.5),
            "xy_p95_m": _q(final_xy, 0.95),
            "yaw_p50": _q(final_yaw, 0.5),
            "yaw_p95": _q(final_yaw, 0.95),
        },
        "sim_s_p50_by_corrections": {str(k): _q(v, 0.5) for k, v in sim_by_corr.items()},
        "refine_failed_last_step": refine_failed,
    }


def attempts(log: Path) -> dict:
    """``<time> <episode> <job> attempt <k> exit <code>`` lines of ``docker/nav_b1.sh``."""
    rows = [ln.split() for ln in log.read_text().splitlines() if " attempt " in ln]
    codes = Counter(r[-1] for r in rows)
    retried = sorted({(r[1], r[2]) for r in rows if r[-1] != "0"})
    return {
        "attempts": len(rows),
        "exit_codes": dict(sorted(codes.items())),
        "jobs_retried": len(retried),
        "jobs_never_succeeded": sorted(
            f"{e}/{j}"
            for e, j in retried
            if not any(r[1] == e and r[2] == j and r[-1] == "0" for r in rows)
        ),
        "first": rows[0][0] if rows else None,
        "last": rows[-1][0] if rows else None,
    }


def b0_lineage(results: Path) -> list[dict]:
    out = []
    for ns in B0_NAMESPACES:
        r = json.loads((results / ns / "b0_report.json").read_text())
        c, nav = r["criteria"], r["navigation"]
        d016 = r.get("decision_016")
        out.append(
            {
                "namespace": ns,
                "verdict": r["verdict"],
                "arrival_rate": c["C3_nav_success_rate"],
                "collisions": c["C3_collisions"],
                "loc_xy_p95_m": c["C4_loc_xy_p95_m"],
                "loc_yaw_p95": c["C4_loc_yaw_p95"],
                "wrong_definitive": c["C6_wrong_definitive"],
                "geometric_risk_pairs": c["C6_geometric_risk"],
                "amcl_all_views_risk_episodes": r["decisions"]["all_views_geometric_risk_episodes"],
                "d016_all_views_risk_episodes": d016["R2_all_views_geometric_risk"]
                if d016
                else None,
                "refined_xy_p95_m": d016["refinement"]["ok_xy_p95_m"] if d016 else None,
                "refined_ok": [d016["refinement"]["ok"], d016["refinement"]["captures"]]
                if d016
                else None,
                "goal_sim_s_p50": nav["goal_sim_s_p50"],
                "relocalized": "relocalized_goals" in nav,
            }
        )
    return out


def cost_per_episode(navs: list[dict], specs) -> dict:
    """Per episode (Random: mean of seeds): path length and navigation time, Rule vs Random."""
    out: dict = {"episodes": [s.episode_id for s in specs]}
    for field in ("path_m", "sim_s"):
        for m in ("rule", "random"):
            seeds = RANDOM_SEEDS if m == "random" else (0,)
            out[f"{m}_{field}"] = [
                round(
                    float(
                        np.mean(
                            [
                                sum(
                                    n[field]
                                    for n in navs
                                    if n["episode"] == s.episode_id
                                    and n["method"] == m
                                    and n["seed"] == sd
                                )
                                for sd in seeds
                            ]
                        )
                    ),
                    4,
                )
                for s in specs
            ]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.nav.failure_analysis")
    ap.add_argument("--ns", default="nav-b2")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    from ..detector.cache import DetectionCache
    from ..framestore import FrameStore
    from ..serialize import load_episode_set
    from ..sim.replay import GazeboReplayWorld
    from .b1_analysis import nav_outcomes, teleport_outcomes

    ns, runs = args.ns, Path("runs") / args.ns
    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    world = GazeboReplayWorld(
        FrameStore(f"renders/{ns}"), DetectionCache.load(f"runs/{ns}/teleport-detector-v1.jsonl")
    )
    tel = teleport_outcomes(specs, gts, world)
    nav, navs, missing = nav_outcomes(runs, specs)
    if missing:
        raise SystemExit(f"{len(missing)} runs missing under {runs}")
    summary = {
        "namespace": ns,
        "note": "post hoc, read-only: explains the committed decision 019 numbers; nothing rerun",
        "discordant_formal_budgets": discordant(nav, tel, specs, gts, world, runs, FORMAL_BUDGETS),
        "relocalization": relocalization(runs, specs),
        "capture_refinement": capture_refinement(runs, specs),
        "attempts": attempts(runs / "attempts.log"),
        "b0_lineage": b0_lineage(Path("results")),
        "cost_per_episode": cost_per_episode(navs, specs),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    for r in summary["discordant_formal_budgets"]:
        print(r["method"], r["seed"], r["budget"], r["episode"], r["state"], r["cause"])
    print(json.dumps(summary["relocalization"], indent=1))
    print(json.dumps(summary["attempts"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
