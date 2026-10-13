"""Decision-008 tuning protocol. NEVER touches the test split (hard guard).

    python -m activeperception.tune decision --episodes data/episodes/gazebo-core.json \\
        --detections runs/core/detector-v1.jsonl --out results/tuning
    python -m activeperception.tune rule --episodes ... --detections ... --out results/tuning
    python -m activeperception.tune val  --episodes ... --detections ... --out results/tuning
    python -m activeperception.tune {decision2,rule2,val2} ... --out results/tuning-v2  # 011

Stage 1 (``decision``): grid over the shared decision rule using Random-NBV observations
(run seeds 0-4) at budgets {3, 5} on train; maximise mean accuracy subject to
false-absent = 0 and false-present <= 1 %; tie-breaks per decision 008.
Stage 2 (``rule``): decision-v1 fixed (read from stage 1); grid over rule-NBV weights on
train at budgets {3, 5}; maximise mean accuracy subject to false-absent no higher than
Random NBV at the same budget; tie-breaks: fewer non-zero weights, fewer viewpoints.
Stage 3 (``val``): all four methods on val, budgets 1-8; report only, no tuning.
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
from pathlib import Path

import numpy as np

from .decision import DecisionRule, DecisionRuleParams
from .grader import grade
from .harness import run_episode
from .policies import (
    OracleNBVPolicy,
    RandomNBVPolicy,
    RuleNBVParams,
    RuleNBVPolicy,
    SingleViewPolicy,
)
from .serialize import load_episode_set
from .sim.replay import GazeboReplayWorld
from .types import Split

TUNE_BUDGETS = (3, 5)
RANDOM_SEEDS = (0, 1, 2, 3, 4)
ACC_TIE = 0.005
FALSE_PRESENT_MAX = 0.01


def guard_split(split: Split) -> None:
    if split == Split.TEST:
        raise SystemExit("tuning never runs on the test split (decision 008)")
    if split == Split.HOLDOUT:
        raise SystemExit("tuning never runs on the holdout split (decision 011)")


def load(episodes: str, detections: str, renders: str | None, split: Split):
    from .detector.cache import DetectionCache
    from .framestore import FrameStore

    guard_split(split)
    specs, gts, meta = load_episode_set(episodes)
    specs = [s for s in specs if s.split == split]
    if not specs:
        raise SystemExit(f"no episodes in split {split}")
    world = GazeboReplayWorld(
        FrameStore(renders or meta["renders"]), DetectionCache.load(detections)
    )
    return specs, gts, world


def evaluate(specs, gts, world, make_policy, rule, budgets, seeds=(0,)) -> dict:
    """Mean metrics per budget over run seeds."""
    by_id = {s.episode_id: s for s in specs}
    out = {}
    for b in budgets:
        rows = []
        for seed in seeds:
            pol = make_policy()
            outs = [
                grade(
                    run_episode(s, world, pol, rule, b, seed),
                    gts[s.episode_id],
                    by_id[s.episode_id],
                )
                for s in specs
            ]
            present = [o for o in outs if o.gt_state != "absent"]
            absent = [o for o in outs if o.gt_state == "absent"]
            rows.append(
                {
                    "accuracy": float(np.mean([o.correct for o in outs])),
                    "false_absent_rate": float(np.mean([o.false_absent for o in present])),
                    "false_present_rate": float(np.mean([o.false_present for o in absent])),
                    "inconclusive_rate": float(np.mean([o.inconclusive for o in outs])),
                    "avg_viewpoints": float(np.mean([o.viewpoints_used for o in outs])),
                }
            )
        out[str(b)] = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
        out[str(b)]["false_absent_rate_max_over_seeds"] = max(r["false_absent_rate"] for r in rows)
        out[str(b)]["false_present_rate_max_over_seeds"] = max(
            r["false_present_rate"] for r in rows
        )
    return out


def decision_grid():
    for tau_p, tau_a in itertools.product((0.3, 0.4, 0.5, 0.6, 0.7), (0.05, 0.1, 0.2, 0.3)):
        if tau_a > tau_p:
            continue
        for n, k in ((4, 2), (4, 3), (6, 2), (6, 3), (6, 4), (8, 2), (8, 3), (8, 4)):
            for eff in (0.3, 0.5, 0.7):
                yield DecisionRuleParams(
                    tau_present=tau_p,
                    tau_absent=tau_a,
                    n_sectors=n,
                    min_coverage=k / n,
                    effective_zone_fraction=eff,
                )


def stage_decision(specs, gts, world) -> dict:
    results = []
    for dp in decision_grid():
        m = evaluate(
            specs, gts, world, RandomNBVPolicy, DecisionRule(dp), TUNE_BUDGETS, RANDOM_SEEDS
        )
        feasible = all(
            m[str(b)]["false_absent_rate_max_over_seeds"] == 0.0
            and m[str(b)]["false_present_rate_max_over_seeds"] <= FALSE_PRESENT_MAX
            for b in TUNE_BUDGETS
        )
        acc = float(np.mean([m[str(b)]["accuracy"] for b in TUNE_BUDGETS]))
        results.append(
            {"params": dataclasses.asdict(dp), "metrics": m, "feasible": feasible, "accuracy": acc}
        )
    feasible = [r for r in results if r["feasible"]]
    if not feasible:
        raise SystemExit("no decision-rule configuration satisfies the constraints")
    best_acc = max(r["accuracy"] for r in feasible)
    tied = [r for r in feasible if best_acc - r["accuracy"] <= ACC_TIE]
    tied.sort(
        key=lambda r: (
            -r["params"]["min_coverage"],
            -r["params"]["tau_present"],
            -r["params"]["effective_zone_fraction"],
            -r["accuracy"],
        )
    )
    return {
        "best": tied[0],
        "n_configs": len(results),
        "n_feasible": len(feasible),
        "tied": len(tied),
        "all": results,
    }


def rule_grid():
    for wc, wv, wn, wa, wu in itertools.product(
        (0.0, 0.5, 1.0, 2.0), (0.0, 0.5, 1.0, 2.0), (0.0, 0.5, 1.0), (0.0, 1.0), (0.0, 0.5)
    ):
        yield RuleNBVParams(
            w_coverage=wc, w_visibility=wv, w_novelty=wn, w_attraction=wa, w_unobstructed=wu
        )


def stage_rule(specs, gts, world, dp: DecisionRuleParams) -> dict:
    rule = DecisionRule(dp)
    random_ref = evaluate(specs, gts, world, RandomNBVPolicy, rule, TUNE_BUDGETS, RANDOM_SEEDS)
    cache: dict = {}  # predicted visibility, shared across configs on the same world
    results = []
    for rp in rule_grid():
        m = evaluate(
            specs, gts, world, lambda rp=rp: RuleNBVPolicy(rp, dp, cache), rule, TUNE_BUDGETS
        )
        feasible = all(
            m[str(b)]["false_absent_rate"] <= random_ref[str(b)]["false_absent_rate"]
            for b in TUNE_BUDGETS
        )
        weights = [rp.w_coverage, rp.w_visibility, rp.w_novelty, rp.w_attraction, rp.w_unobstructed]
        results.append(
            {
                "params": dataclasses.asdict(rp),
                "metrics": m,
                "feasible": feasible,
                "accuracy": float(np.mean([m[str(b)]["accuracy"] for b in TUNE_BUDGETS])),
                "avg_viewpoints": float(
                    np.mean([m[str(b)]["avg_viewpoints"] for b in TUNE_BUDGETS])
                ),
                "n_nonzero": sum(w != 0 for w in weights),
            }
        )
    feasible = [r for r in results if r["feasible"]]
    best_acc = max(r["accuracy"] for r in feasible)
    tied = [r for r in feasible if best_acc - r["accuracy"] <= ACC_TIE]
    tied.sort(key=lambda r: (r["n_nonzero"], r["avg_viewpoints"], -r["accuracy"]))
    return {
        "best": tied[0],
        "random_reference": random_ref,
        "n_configs": len(results),
        "n_feasible": len(feasible),
        "tied": len(tied),
        "all": results,
    }


def stage_val(specs, gts, world, dp, rp, budgets=tuple(range(1, 9))) -> dict:
    rule = DecisionRule(dp)
    methods = {
        "single": (SingleViewPolicy, (0,)),
        "random": (RandomNBVPolicy, RANDOM_SEEDS),
        "rule": (lambda: RuleNBVPolicy(rp, dp), (0,)),
        "oracle": (lambda: OracleNBVPolicy(gts.__getitem__, dp), (0,)),
    }
    return {
        name: evaluate(specs, gts, world, make, rule, budgets, seeds)
        for name, (make, seeds) in methods.items()
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.tune")
    ap.add_argument("stage", choices=["decision", "rule", "val", "decision2", "rule2", "val2"])
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--detections", required=True)
    ap.add_argument("--renders")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.stage.endswith("2"):
        return main_v2(args, out)
    split = Split.VAL if args.stage == "val" else Split.TRAIN
    specs, gts, world = load(args.episodes, args.detections, args.renders, split)
    if args.stage == "decision":
        res = stage_decision(specs, gts, world)
        (out / "stage1_decision.json").write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k != "all"}, indent=1))
        return 0
    s1 = json.loads((out / "stage1_decision.json").read_text())
    dp = DecisionRuleParams(**s1["best"]["params"])
    if args.stage == "rule":
        res = stage_rule(specs, gts, world, dp)
        (out / "stage2_rule.json").write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k != "all"}, indent=1))
        return 0
    s2 = json.loads((out / "stage2_rule.json").read_text())
    rp = RuleNBVParams(**s2["best"]["params"])
    res = stage_val(specs, gts, world, dp, rp)
    (out / "stage3_val.json").write_text(json.dumps(res, indent=1))
    for name, per_b in res.items():
        print(name, {b: round(m["accuracy"], 3) for b, m in per_b.items()})
    return 0


# ---- v2 (decision 011 section 6): train only, the v1 functions above are unchanged -------
V2_BUDGETS = (2, 3, 5)
V2_DECISION_TIE = 0.01
V2_RULE_TIE = 0.005


def geometric_risk(record, gt, rule) -> bool:
    """Object present, absent geometry satisfied, yet never visible in a visited view."""
    if not gt.object_present or not rule.absent_geometry(record.observations):
        return False
    vis = [
        gt.visibility_initial if vid == -1 else gt.visibility_by_viewpoint.get(vid, 0.0)
        for vid in record.viewpoint_sequence
    ]
    return max(vis) < 0.1


def evaluate_v2(specs, gts, world, make_policy, rule, budgets, seeds=(0,)) -> dict:
    """``evaluate`` plus the geometric false-absent risk count (decision 011)."""
    by_id = {s.episode_id: s for s in specs}
    out = {}
    for b in budgets:
        rows = []
        for seed in seeds:
            pol = make_policy()
            recs = [run_episode(s, world, pol, rule, b, seed) for s in specs]
            outs = [grade(r, gts[r.episode_id], by_id[r.episode_id]) for r in recs]
            present = [o for o in outs if o.gt_state != "absent"]
            absent = [o for o in outs if o.gt_state == "absent"]
            rows.append(
                {
                    "accuracy": float(np.mean([o.correct for o in outs])),
                    "false_absent_rate": float(np.mean([o.false_absent for o in present])),
                    "false_present_rate": float(np.mean([o.false_present for o in absent])),
                    "inconclusive_rate": float(np.mean([o.inconclusive for o in outs])),
                    "avg_viewpoints": float(np.mean([o.viewpoints_used for o in outs])),
                    "geometric_risk": int(
                        sum(geometric_risk(r, gts[r.episode_id], rule) for r in recs)
                    ),
                }
            )
        m = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
        m["false_absent_rate_max_over_seeds"] = max(r["false_absent_rate"] for r in rows)
        m["false_present_rate_max_over_seeds"] = max(r["false_present_rate"] for r in rows)
        m["geometric_risk_total"] = int(sum(r["geometric_risk"] for r in rows))
        out[str(b)] = m
    return out


def decision_v2_grid():
    from .decision import DecisionRuleV2Params

    for tp, ta, tc, cm in itertools.product(
        (0.5, 0.7), (0.02, 0.05), (0.9, 0.95, 1.0), (2 / 3, 1.0)
    ):
        yield DecisionRuleV2Params(tau_present=tp, tau_absent=ta, tau_clear=tc, col_min=cm)


def stage_decision_v2(specs, gts, world) -> dict:
    from .decision import DecisionRuleV2

    results = []
    for dp in decision_v2_grid():
        m = evaluate_v2(
            specs, gts, world, RandomNBVPolicy, DecisionRuleV2(dp), V2_BUDGETS, RANDOM_SEEDS
        )
        feasible = all(
            m[str(b)]["false_absent_rate_max_over_seeds"] == 0.0
            and m[str(b)]["geometric_risk_total"] == 0
            and m[str(b)]["false_present_rate_max_over_seeds"] <= FALSE_PRESENT_MAX
            for b in V2_BUDGETS
        )
        acc = float(np.mean([m[str(b)]["accuracy"] for b in V2_BUDGETS]))
        results.append(
            {"params": dataclasses.asdict(dp), "metrics": m, "feasible": feasible, "accuracy": acc}
        )
    feasible = [r for r in results if r["feasible"]]
    if not feasible:
        raise SystemExit("no decision-v2 configuration satisfies the constraints")
    best_acc = max(r["accuracy"] for r in feasible)
    tied = [r for r in feasible if best_acc - r["accuracy"] <= V2_DECISION_TIE]
    tied.sort(
        key=lambda r: (
            -r["params"]["tau_clear"],
            -r["params"]["col_min"],
            r["params"]["tau_absent"],
            -r["params"]["tau_present"],
            -r["accuracy"],
        )
    )
    return {
        "best": tied[0],
        "n_configs": len(results),
        "n_feasible": len(feasible),
        "tied": len(tied),
        "all": results,
    }


def rule_v2_grid():
    from .policies import RuleNBVv2Params

    for wg, pu, wn, wa, wv in itertools.product(
        (0.0, 1.0, 2.0), (0.0, 0.25, 0.5, 1.0), (0.0, 0.25, 0.5), (0.0, 0.5), (0.0, 0.5)
    ):
        yield RuleNBVv2Params(
            w_gain=wg, p_unknown=pu, w_novelty=wn, w_attraction=wa, w_visibility=wv
        )


def stage_rule_v2(specs, gts, world, dp) -> dict:
    from .decision import DecisionRuleV2
    from .policies import RuleNBVv2Policy

    rule = DecisionRuleV2(dp)
    random_ref = evaluate_v2(specs, gts, world, RandomNBVPolicy, rule, V2_BUDGETS, RANDOM_SEEDS)
    cache: dict = {}
    results = []
    for rp in rule_v2_grid():
        m = evaluate_v2(
            specs, gts, world, lambda rp=rp: RuleNBVv2Policy(rp, dp, cache), rule, V2_BUDGETS
        )
        feasible = all(
            m[str(b)]["false_absent_rate"] <= random_ref[str(b)]["false_absent_rate"]
            and m[str(b)]["geometric_risk_total"] == 0
            for b in V2_BUDGETS
        )
        weights = [rp.w_gain, rp.w_novelty, rp.w_attraction, rp.w_visibility]
        results.append(
            {
                "params": dataclasses.asdict(rp),
                "metrics": m,
                "feasible": feasible,
                "accuracy": float(np.mean([m[str(b)]["accuracy"] for b in V2_BUDGETS])),
                "avg_viewpoints": float(np.mean([m[str(b)]["avg_viewpoints"] for b in V2_BUDGETS])),
                "n_nonzero": sum(w != 0 for w in weights),
            }
        )
    feasible = [r for r in results if r["feasible"]]
    best_acc = max(r["accuracy"] for r in feasible)
    tied = [r for r in feasible if best_acc - r["accuracy"] <= V2_RULE_TIE]
    tied.sort(
        key=lambda r: (
            r["n_nonzero"],
            r["avg_viewpoints"],
            r["params"]["p_unknown"],
            -r["accuracy"],
        )
    )
    return {
        "best": tied[0],
        "random_reference": random_ref,
        "n_configs": len(results),
        "n_feasible": len(feasible),
        "tied": len(tied),
        "all": results,
    }


def stage_val_v2(specs, gts, world, dp, rp, budgets=tuple(range(1, 9))) -> dict:
    from .decision import DecisionRuleV2
    from .policies import OracleNBVv2Policy, RuleNBVv2Policy
    from .sim.replay import make_peek

    rule = DecisionRuleV2(dp)
    peek = make_peek(world, specs)
    methods = {
        "single": (SingleViewPolicy, (0,)),
        "random": (RandomNBVPolicy, RANDOM_SEEDS),
        "rule": (lambda: RuleNBVv2Policy(rp, dp), (0,)),
        "oracle": (lambda: OracleNBVv2Policy(gts.__getitem__, peek, dp), (0,)),
    }
    return {
        name: evaluate_v2(specs, gts, world, make, rule, budgets, seeds)
        for name, (make, seeds) in methods.items()
    }


def main_v2(args, out: Path) -> int:
    from .decision import DecisionRuleV2Params
    from .policies import RuleNBVv2Params

    split = Split.VAL if args.stage == "val2" else Split.TRAIN
    specs, gts, world = load(args.episodes, args.detections, args.renders, split)
    if args.stage == "decision2":
        res = stage_decision_v2(specs, gts, world)
        (out / "stage1_decision_v2.json").write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k != "all"}, indent=1))
        return 0
    s1 = json.loads((out / "stage1_decision_v2.json").read_text())
    dp = DecisionRuleV2Params(**s1["best"]["params"])
    if args.stage == "rule2":
        res = stage_rule_v2(specs, gts, world, dp)
        (out / "stage2_rule_v2.json").write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k != "all"}, indent=1))
        return 0
    s2 = json.loads((out / "stage2_rule_v2.json").read_text())
    rp = RuleNBVv2Params(**s2["best"]["params"])
    res = stage_val_v2(specs, gts, world, dp, rp)
    (out / "stage3_val_v2.json").write_text(json.dumps(res, indent=1))
    for name, per_b in res.items():
        print(name, {b: round(m["accuracy"], 3) for b, m in per_b.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
