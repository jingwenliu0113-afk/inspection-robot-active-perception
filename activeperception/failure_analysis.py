"""Failure analysis across the sealed formal runs (decision 014). Reads committed files only.

    python -m activeperception.failure_analysis --out results/failure-analysis

Inputs: ``results/test-v1/`` (v1 on the core test split) and ``results/holdout/`` (v1, v2 and the
ablation on the holdout split), plus the episode sets for scene descriptors. Nothing is
re-run, so neither sealed split is evaluated again, and nothing here feeds back into any
frozen parameter (decision 014: no tuning on test or holdout results).

Datasets are reported side by side, never pooled: ``test/v1``, ``holdout/v1``,
``holdout/v2``, ``holdout/ablation`` (decision-v2 + rule-nbv-v1, Rule only).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .serialize import read_jsonl

BUDGETS = (2, 3)
STATES = ("visible", "unobservable", "absent")
INITIAL_BLOCKED = 0.3  # decision-v1 "effective view" threshold on zone visibility
DATASETS = {
    # name: (outcomes file, config in that file, oracle config with the same decision rule)
    "test/v1": ("results/test-v1/outcomes.jsonl", "v1", "v1"),
    "holdout/v1": ("results/holdout/outcomes.jsonl", "v1", "v1"),
    "holdout/v2": ("results/holdout/outcomes.jsonl", "v2", "v2"),
    "holdout/ablation": ("results/holdout/outcomes.jsonl", "ablation", "v2"),
}
EPISODE_SETS = {
    "test": "data/episodes/gazebo-core.json",
    "holdout": "data/episodes/gazebo-holdout.json",
}


def load_outcomes(root: Path) -> dict[str, list[dict]]:
    """Outcome rows per source file; rows without ``config`` (v1 test file) get ``v1``."""
    out = {}
    for path, _, _ in DATASETS.values():
        if path not in out:
            rows = read_jsonl(root / path)
            for r in rows:
                r.setdefault("config", "v1")
            out[path] = rows
    return out


def select(rows: list[dict], config: str, method: str, budget: int) -> list[dict]:
    return [
        r for r in rows if r["config"] == config and r["method"] == method and r["budget"] == budget
    ]


def error_matrix(rows: list[dict]) -> dict:
    """Decision counts per GT state (summed over seeds) and the per-seed-averaged rates."""
    n_seeds = len({r["seed"] for r in rows}) or 1
    by_state: dict[str, Counter] = {s: Counter() for s in STATES}
    for r in rows:
        by_state[r["gt_state"]][r["decision"]] += 1
    return {
        "n_seeds": n_seeds,
        "decisions_by_state": {s: dict(sorted(c.items())) for s, c in by_state.items()},
        "wrong_definitive": sum(1 for r in rows if not r["correct"] and not r["inconclusive"]),
        "inconclusive": sum(1 for r in rows if r["inconclusive"]),
        "false_absent": sum(1 for r in rows if r["false_absent"]),
        "false_present": sum(1 for r in rows if r["false_present"]),
        "n": len(rows) // n_seeds,
    }


def attribution(rule_rows: list[dict], oracle_rows: list[dict]) -> dict:
    """Rule failures split by whether the oracle (same decision rule, same budget) succeeds.

    ``policy_gap``: the oracle is correct -> a better choice among the same candidates
    would have answered (viewpoint selection). ``structural``: the oracle fails as well ->
    the budget / decision rule cannot answer with any candidate choice.
    """
    oracle = {r["episode_id"]: r["correct"] for r in oracle_rows}
    fails = [r for r in rule_rows if not r["correct"]]
    gap = [r for r in fails if oracle[r["episode_id"]]]
    structural = [r for r in fails if not oracle[r["episode_id"]]]
    return {
        "n_episodes": len(rule_rows),
        "rule_failures": len(fails),
        "policy_gap": len(gap),
        "structural": len(structural),
        "policy_gap_by_state": dict(sorted(Counter(r["gt_state"] for r in gap).items())),
        "structural_by_state": dict(sorted(Counter(r["gt_state"] for r in structural).items())),
        "policy_gap_wrong_definitive": sum(1 for r in gap if not r["inconclusive"]),
        "policy_gap_episodes": sorted(r["episode_id"] for r in gap),
    }


def transitions(a_rows: list[dict], b_rows: list[dict]) -> dict:
    """Paired per-episode correctness, A -> B (same episodes, deterministic methods)."""
    a = {r["episode_id"]: r["correct"] for r in a_rows}
    b = {r["episode_id"]: r["correct"] for r in b_rows}
    assert a.keys() == b.keys()
    fixed = sorted(e for e in a if not a[e] and b[e])
    broken = sorted(e for e in a if a[e] and not b[e])
    return {
        "both_correct": sum(1 for e in a if a[e] and b[e]),
        "both_wrong": sum(1 for e in a if not a[e] and not b[e]),
        "fixed": len(fixed),
        "broken": len(broken),
        "broken_episodes": broken,
    }


def false_absent_cases(rows: list[dict]) -> list[dict]:
    keys = ("config", "method", "budget", "seed", "episode_id", "gt_state")
    return [{k: r[k] for k in keys} for r in rows if r["false_absent"]]


def scene_descriptors(episode_set: dict) -> dict[str, dict]:
    """Deployment-independent scene facts used only to slice failures (never by a policy)."""
    out = {}
    for e in episode_set["episodes"]:
        gt, spec = e["ground_truth"], e["spec"]
        zone_init = gt["zone_visible_by_viewpoint"]["-1"]
        out[spec["episode_id"]] = {
            "n_occluders": len(spec["layout"]["occluders"]),
            "initial_zone_blocked": zone_init < INITIAL_BLOCKED,
        }
    return out


def failure_slices(rule_rows: list[dict], scenes: dict[str, dict]) -> dict:
    """Rule failure rate by occluder count and by whether the initial view sees the zone."""
    slices: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rule_rows:
        d = scenes[r["episode_id"]]
        for name, key in (
            ("n_occluders", str(d["n_occluders"])),
            ("initial_zone_blocked", str(d["initial_zone_blocked"]).lower()),
        ):
            cell = slices[name][key]
            cell[0] += 0 if r["correct"] else 1
            cell[1] += 1
    return {
        name: {
            k: {"failures": f, "n": n, "rate": round(f / n, 4)} for k, (f, n) in sorted(v.items())
        }
        for name, v in slices.items()
    }


def analyze(root: Path) -> dict:
    files = load_outcomes(root)
    scenes = {}
    for path in EPISODE_SETS.values():
        scenes.update(scene_descriptors(json.loads((root / path).read_text())))
    report: dict = {"budgets": list(BUDGETS), "datasets": {}}
    for name, (path, config, oracle_config) in DATASETS.items():
        rows = files[path]
        methods = ("rule",) if config == "ablation" else ("single", "random", "rule", "oracle")
        block: dict = {"source": path, "config": config, "errors": {}, "rule": {}}
        for b in BUDGETS:
            block["errors"][str(b)] = {m: error_matrix(select(rows, config, m, b)) for m in methods}
            rule_rows = select(rows, config, "rule", b)
            block["rule"][str(b)] = {
                "attribution": attribution(rule_rows, select(rows, oracle_config, "oracle", b)),
                "slices": failure_slices(rule_rows, scenes),
            }
        block["false_absent_cases"] = false_absent_cases([r for r in rows if r["config"] == config])
        report["datasets"][name] = block
    hold = files[DATASETS["holdout/v2"][0]]
    report["holdout_paired"] = {
        str(b): {
            "v1_rule_to_v2_rule": transitions(
                select(hold, "v1", "rule", b), select(hold, "v2", "rule", b)
            ),
            "decision_effect_v1_rule_to_ablation": transitions(
                select(hold, "v1", "rule", b), select(hold, "ablation", "rule", b)
            ),
            "policy_effect_ablation_to_v2_rule": transitions(
                select(hold, "ablation", "rule", b), select(hold, "v2", "rule", b)
            ),
        }
        for b in BUDGETS
    }
    return report


def score_ties(policy, episode, history) -> dict:
    """How many unvisited candidates share the top rule-nbv-v2 score at this decision point."""
    from .policies.base import unvisited_candidates
    from .sensing import cleared_locations

    p = policy.params
    uncleared = ~cleared_locations(history, policy.dp.col_min)
    scores = {}
    for vp in unvisited_candidates(episode, history):
        f = policy.features(episode, history, vp, uncleared)
        scores[vp.id] = (
            p.w_gain * f["clear_gain"]
            + p.w_novelty * f["novelty"]
            + p.w_attraction * f["attraction"]
            + p.w_visibility * f.get("predicted_visibility", 0.0)
        )
    best = max(scores.values())
    tied = sorted(i for i, s in scores.items() if abs(s - best) < 1e-12)
    return {"n_candidates": len(scores), "n_tied": len(tied), "chosen": tied[0]}


def dev_tie_analysis(specs, gts, world) -> dict:
    """Second-view choice of the frozen rule-nbv-v2 on DEVELOPMENT data (core train / val).

    Counts decision points where several candidates share the top score, so the choice falls
    to the lowest candidate id (``sorted(scored)[0]``), split by whether the initial view saw
    the zone. Reporting only: nothing here changes a frozen parameter (decision 014).
    """
    from . import frozen_v2
    from .grader import grade
    from .harness import run_episode

    rule = frozen_v2.decision_rule()
    cache: dict = {}
    policy = frozen_v2.rule_nbv(cache)
    cells: dict[str, dict[str, int]] = defaultdict(Counter)
    for s in specs:
        episode = s.deployable()
        history = (world.observe(s, s.initial_viewpoint),)
        if rule.decide(episode, list(history)).decision.value != "inconclusive":
            continue
        t = score_ties(policy, episode, history)
        blocked = gts[s.episode_id].zone_visible_by_viewpoint[-1] < INITIAL_BLOCKED
        correct = grade(run_episode(s, world, policy, rule, 2), gts[s.episode_id], s).correct
        key = f"initial_zone_blocked={str(blocked).lower()}"
        c = cells[key]
        c["decision_points"] += 1
        c["tied"] += t["n_tied"] > 1
        c["all_tied"] += t["n_tied"] == t["n_candidates"]
        c["n_tied_sum"] += t["n_tied"]
        c["n_candidates_sum"] += t["n_candidates"]
        c["budget2_correct"] += correct
        c["budget2_correct_when_tied"] += correct and t["n_tied"] > 1
    return {k: dict(v) for k, v in sorted(cells.items())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.failure_analysis")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dev-episodes", help="core episode set for the dev-data tie analysis")
    ap.add_argument("--dev-detections")
    ap.add_argument("--dev-renders")
    args = ap.parse_args(argv)
    report = analyze(Path(args.root))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.dev_episodes:
        from .tune import load
        from .types import Split

        report["dev_rule_nbv_v2_ties"] = {}
        for split in (Split.TRAIN, Split.VAL):  # load() refuses TEST and HOLDOUT
            specs, gts, world = load(
                args.dev_episodes, args.dev_detections, args.dev_renders, split
            )
            report["dev_rule_nbv_v2_ties"][str(split)] = dev_tie_analysis(specs, gts, world)
        print(json.dumps(report["dev_rule_nbv_v2_ties"], indent=1))
    (out / "summary.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    for name, block in report["datasets"].items():
        for b in BUDGETS:
            a = block["rule"][str(b)]["attribution"]
            print(
                f"{name:18s} b{b}: rule failures {a['rule_failures']:3d} = "
                f"policy gap {a['policy_gap']:3d} + structural {a['structural']:3d}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
