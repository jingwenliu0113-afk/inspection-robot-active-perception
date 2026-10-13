"""Holdout comparison of v1 and v2 (decisions 011 section 7 and 012). One shot.

    python -m activeperception.experiment_v2 holdout --episodes data/episodes/gazebo-holdout.json \\
        --detections runs/holdout/detector-v1.jsonl --renders renders/holdout --out results/holdout
    python -m activeperception.experiment_v2 dryrun ...   # identical pipeline on core VAL

Configurations: v1 (the frozen v1 code path, ``experiment.run_all``), v2 (decision-v2 +
rule-nbv-v2 + oracle-v2 with Single / Random), and the ablation decision-v2 + rule-nbv-v1.
Never runs on the sealed v1 test split; refuses an existing output directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from . import experiment, frozen, frozen_v2, seal
from .detector.cache import DetectionCache
from .framestore import FrameStore
from .grader import grade
from .harness import run_episode
from .metrics import reliability_bins
from .policies import OracleNBVv2Policy, RandomNBVPolicy, SingleViewPolicy
from .sensing import cleared_locations
from .serialize import load_episode_set, write_jsonl
from .sim.replay import GazeboReplayWorld, make_peek
from .types import Split

STATS_CI = ("accuracy", "false_absent_rate", "inconclusive_rate")


def _run(specs, gts, world, rule, makers, budgets) -> experiment.Runs:
    runs = experiment.Runs(specs)
    by_id = {s.episode_id: s for s in specs}
    for method, (make, seeds) in makers.items():
        for b in budgets:
            per_seed, recs = [], []
            for seed in seeds:
                pol = make()
                rs = [run_episode(s, world, pol, rule, b, seed) for s in specs]
                per_seed.append([grade(r, gts[r.episode_id], by_id[r.episode_id]) for r in rs])
                recs.append(rs)
            runs.outcomes[method][b] = per_seed
            runs.records[method][b] = recs
    return runs


def run_v2(specs, gts, world, budgets) -> experiment.Runs:
    cache: dict = {}
    peek = make_peek(world, specs)
    makers = {
        "single": (SingleViewPolicy, (0,)),
        "random": (RandomNBVPolicy, frozen_v2.RANDOM_SEEDS),
        "rule": (lambda: frozen_v2.rule_nbv(cache), (0,)),
        "oracle": (lambda: OracleNBVv2Policy(gts.__getitem__, peek, frozen_v2.DECISION_V2), (0,)),
    }
    return _run(specs, gts, world, frozen_v2.decision_rule(), makers, budgets)


def run_ablation(specs, gts, world, budgets) -> experiment.Runs:
    cache: dict = {}
    makers = {"rule": (lambda: frozen.rule_nbv(cache), (0,))}
    return _run(specs, gts, world, frozen_v2.decision_rule(), makers, budgets)


def summarize(runs, methods, budgets, n_boot, boot_budgets) -> dict:
    idx = np.arange(len(runs.specs))
    out = {}
    for m in methods:
        for b in budgets:
            row = {k: runs.stat(m, b, k, idx) for k in experiment.REPORT_STATS}
            if b in boot_budgets:
                for k in STATS_CI:
                    row[f"{k}_ci95"] = experiment.bootstrap(
                        runs,
                        lambda i, m=m, b=b, k=k: runs.stat(m, b, k, i),
                        n_boot,
                        frozen.BOOT_SEED,
                    )
            out[f"{m}@{b}"] = row
    return out


def cross_diff(a, b, method_a, method_b, budget, stat, n_boot) -> dict:
    """a[method_a] - b[method_b] on the same episodes and the same bootstrap resamples."""

    def fn(idx):
        va, vb = a.stat(method_a, budget, stat, idx), b.stat(method_b, budget, stat, idx)
        return None if va is None or vb is None else va - vb

    return {
        "diff": fn(np.arange(len(a.specs))),
        "ci95": experiment.bootstrap(a, fn, n_boot, frozen.BOOT_SEED),
    }


def wasted_views(runs, budget: int, col_min: float) -> tuple[np.ndarray, np.ndarray]:
    """Per episode: (non-initial rule views that saw through no new location, non-initial views)."""
    wasted, total = [], []
    for rec in runs.records["rule"][budget][0]:
        w = 0
        for k in range(1, len(rec.observations)):
            before = cleared_locations(rec.observations[:k], col_min)
            after = cleared_locations(rec.observations[: k + 1], col_min)
            w += int(not (after & ~before).any())
        wasted.append(w)
        total.append(len(rec.observations) - 1)
    return np.array(wasted), np.array(total)


def wasted_diff(a, b, budget, col_min, n_boot) -> dict:
    wa, ta = wasted_views(a, budget, col_min)
    wb, tb = wasted_views(b, budget, col_min)

    def rate(w, t, idx):
        return float(w[idx].sum() / t[idx].sum()) if t[idx].sum() else None

    def fn(idx):
        ra, rb = rate(wa, ta, idx), rate(wb, tb, idx)
        return None if ra is None or rb is None else ra - rb

    all_idx = np.arange(len(wa))
    return {
        "a_rate": rate(wa, ta, all_idx),
        "b_rate": rate(wb, tb, all_idx),
        "diff": fn(all_idx),
        "ci95": experiment.bootstrap(a, fn, n_boot, frozen.BOOT_SEED),
    }


def geometric_risk(runs, gts, rule, methods, budgets) -> dict:
    out = {}
    for m in methods:
        for b in budgets:
            counts = []
            for recs in runs.records[m][b]:
                n = 0
                for r in recs:
                    g = gts[r.episode_id]
                    if g.object_present and rule.absent_geometry(r.observations):
                        vis = [
                            g.visibility_initial
                            if v == -1
                            else g.visibility_by_viewpoint.get(v, 0.0)
                            for v in r.viewpoint_sequence
                        ]
                        n += max(vis) < 0.1
                counts.append(n)
            out[f"{m}@{b}"] = float(np.mean(counts))
    return out


def failures(runs, gts, budgets=(2, 3)) -> list[dict]:
    rows = experiment.residual_failures(runs, gts, budgets)
    by_key = {(r.episode_id, b): r for b in budgets for r in runs.records["rule"][b][0]}
    for row in rows:
        rec = by_key[(row["episode_id"], row["budget"])]
        row["cleared_fraction"] = rec.features.get("cleared_fraction")
    return rows


def claims(r1, r2, rab, n_boot, budgets) -> dict:
    s_rows = {}
    for m in experiment.METHODS:
        for b in budgets:
            idx = np.arange(len(r1.specs))
            v1, v2 = (
                r1.stat(m, b, "false_absent_rate", idx),
                r2.stat(m, b, "false_absent_rate", idx),
            )
            s_rows[f"{m}@{b}"] = {"v1": v1, "v2": v2, "v2<=v1": bool(v2 <= v1)}
    zero = all(s_rows[f"{m}@{b}"]["v2"] == 0.0 for m in ("rule", "oracle") for b in budgets)
    a_rows = {}
    for b in (2, 3):
        d = cross_diff(r2, r1, "rule", "rule", b, "accuracy", n_boot)
        lo = d["ci95"][0] if d["ci95"] else None
        verdict = (
            "improved"
            if lo is not None and lo > 0
            else "non-inferior"
            if lo is not None and lo > -0.02
            else "worse"
        )
        a_rows[str(b)] = {**d, "verdict": verdict}
    f_rows = {
        str(b): wasted_diff(r2, r1, b, frozen_v2.DECISION_V2.col_min, n_boot) for b in (2, 3, 5)
    }
    ablation = {
        f"{b}": {
            "decision_effect(abl_rule - v1_rule)": cross_diff(
                rab, r1, "rule", "rule", b, "accuracy", n_boot
            ),
            "policy_effect(v2_rule - abl_rule)": cross_diff(
                r2, rab, "rule", "rule", b, "accuracy", n_boot
            ),
        }
        for b in (2, 3)
    }
    return {
        "S_safety": {
            "per_method": s_rows,
            "all_v2_le_v1": all(v["v2<=v1"] for v in s_rows.values()),
            "v2_rule_and_oracle_zero": zero,
        },
        "A_rule_accuracy_v2_minus_v1": a_rows,
        "F_wasted_view_rate_v2_minus_v1": f_rows,
        "ablation": ablation,
    }


def config_block(runs, gts, world, specs, methods, rule, n_boot, budgets, boot_budgets) -> dict:
    block = {
        "summary": summarize(runs, methods, budgets, n_boot, boot_budgets),
        "geometric_false_absent_risk": geometric_risk(runs, gts, rule, methods, boot_budgets),
    }
    if set(methods) == set(experiment.METHODS):
        diffs = experiment.paired_differences(runs, boot_budgets, n_boot)
        fails = failures(runs, gts)
        block.update(
            {
                "paired_differences": diffs,
                "by_state": experiment.by_state(runs, boot_budgets),
                "calibration": {
                    f"{m}@{b}": reliability_bins([o for s in runs.outcomes[m][b] for o in s])
                    for m in methods
                    for b in boot_budgets
                },
                "residual_failures": fails,
                "gate": experiment.gate(diffs, block["summary"], fails),
            }
        )
    return block


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.experiment_v2")
    ap.add_argument("stage", choices=["holdout", "dryrun"], help="dryrun = core VAL")
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--detections", required=True)
    ap.add_argument("--renders")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=frozen.N_BOOT)
    ap.add_argument("--reproduce", action="store_true", help="re-check a sealed run (decision 014)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    split = Split.HOLDOUT if args.stage == "holdout" else Split.VAL
    sealed = seal.guard_formal_run(args.episodes, split, out, args.reproduce)
    if out.exists():
        raise SystemExit(f"{out} exists: the holdout comparison runs once (decision 011)")
    specs, gts, meta = load_episode_set(args.episodes)
    specs = [s for s in specs if s.split == split]
    if not specs:
        raise SystemExit(f"no {split} episodes in {args.episodes}")
    if any(s.split == Split.TEST for s in specs):  # pragma: no cover - guarded by the filter
        raise SystemExit("v2 never runs on the sealed v1 test split")
    world = GazeboReplayWorld(
        FrameStore(args.renders or meta["renders"]), DetectionCache.load(args.detections)
    )
    budgets, formal = frozen.CURVE_BUDGETS, frozen.FORMAL_BUDGETS
    r1 = experiment.run_all(specs, gts, world, budgets)  # the frozen v1 code path
    r2 = run_v2(specs, gts, world, budgets)
    rab = run_ablation(specs, gts, world, formal)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True
    ).stdout
    m4 = experiment.METHODS
    report = {
        "stage": args.stage,
        "split": str(split),
        "git_commit": commit.strip(),
        "git_dirty": bool(dirty.strip()),
        "episode_set": args.episodes,
        "image_ids": meta.get("image_ids"),
        "n_episodes": len(specs),
        "n_groups": len({s.scene_group for s in specs}),
        "versions": {"v1": frozen.VERSIONS, "v2": frozen_v2.VERSIONS},
        "formal_budgets": list(formal),
        "n_boot": args.n_boot,
        "v1": config_block(
            r1, gts, world, specs, m4, frozen.decision_rule(), args.n_boot, budgets, formal
        ),
        "v2": config_block(
            r2, gts, world, specs, m4, frozen_v2.decision_rule(), args.n_boot, budgets, formal
        ),
        "ablation_decision_v2_rule_nbv_v1": config_block(
            rab,
            gts,
            world,
            specs,
            ("rule",),
            frozen_v2.decision_rule(),
            args.n_boot,
            formal,
            formal,
        ),
        "claims": claims(r1, r2, rab, args.n_boot, formal),
        "detector_vs_success": experiment.detector_vs_success(specs, world, 0.7),
    }
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    rows = []
    for name, runs, methods, bs in (
        ("v1", r1, m4, budgets),
        ("v2", r2, m4, budgets),
        ("ablation", rab, ("rule",), formal),
    ):
        for m in methods:
            for b in bs:
                for seed, outs in enumerate(runs.outcomes[m][b]):
                    rows += [
                        {**o.__dict__, "config": name, "method": m, "seed": seed} for o in outs
                    ]
    write_jsonl(out / "outcomes.jsonl", rows)
    print(
        json.dumps(
            {
                "claims": {k: v for k, v in report["claims"].items() if k != "ablation"},
                "gate_v1": report["v1"]["gate"],
                "gate_v2": report["v2"]["gate"],
            },
            indent=1,
            default=str,
        )[:6000]
    )
    if sealed is not None:
        return 0 if seal.compare_reproduction(sealed, out) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
