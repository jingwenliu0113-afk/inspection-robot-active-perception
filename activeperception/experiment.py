"""Formal test run (decision 009): one shot, frozen v1 configuration.

    python -m activeperception.experiment test --episodes data/episodes/gazebo-core.json \\
        --detections runs/core/detector-v1.jsonl --renders renders/core --out results/test-v1

Refuses to run if ``--out`` already exists. Runs Single / Random (seeds 0-4) / Rule-NBV v1 /
Oracle on the test split at budgets 1-8 (formal: {1, 2, 3, 5}), grades every episode and
reports SPEC §7 metrics with scene-group cluster bootstrap CIs, paired method differences,
GT-state strata, calibration, detector size / confidence vs success, residual failures and
the pre-registered Gate checks.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import frozen
from .detector.cache import DetectionCache
from .framestore import FrameStore
from .grader import Outcome, grade
from .harness import run_episode
from .metrics import STATS, reliability_bins
from .policies import OracleNBVPolicy, RandomNBVPolicy, SingleViewPolicy
from .serialize import load_episode_set, write_jsonl
from .sim.replay import GazeboReplayWorld
from .types import GroundTruthState, Split

METHODS = ("single", "random", "rule", "oracle")
REPORT_STATS = (
    "accuracy",
    "macro_f1",
    "false_absent_rate",
    "false_present_rate",
    "inconclusive_rate",
    "avg_viewpoints",
    "ece",
)
DIFF_STATS = ("accuracy", "false_absent_rate", "inconclusive_rate", "avg_viewpoints")
PAIRS = (("rule", "random"), ("rule", "single"), ("oracle", "rule"), ("random", "single"))


class Runs:
    """outcomes[method][budget] = list over seeds of per-episode Outcome lists (aligned)."""

    def __init__(self, specs):
        self.specs = specs
        self.index = {s.episode_id: i for i, s in enumerate(specs)}
        self.groups = np.array([s.scene_group for s in specs])
        self.outcomes: dict[str, dict[int, list[list[Outcome]]]] = defaultdict(dict)
        self.records: dict[str, dict[int, list]] = defaultdict(dict)

    def stat(self, method: str, budget: int, name: str, idx: np.ndarray) -> float | None:
        vals = []
        for seed_outs in self.outcomes[method][budget]:
            v = STATS[name]([seed_outs[i] for i in idx])
            if v is not None:
                vals.append(v)
        return float(np.mean(vals)) if vals else None


def run_all(specs, gts, world, budgets) -> Runs:
    runs = Runs(specs)
    by_id = {s.episode_id: s for s in specs}
    rule = frozen.decision_rule()
    vis_cache: dict = {}
    makers = {
        "single": (SingleViewPolicy, (0,)),
        "random": (RandomNBVPolicy, frozen.RANDOM_SEEDS),
        "rule": (lambda: frozen.rule_nbv(vis_cache), (0,)),
        "oracle": (lambda: OracleNBVPolicy(gts.__getitem__, frozen.DECISION_V1), (0,)),
    }
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


def bootstrap(runs: Runs, fn, n_boot: int, seed: int) -> list[float] | None:
    groups = np.unique(runs.groups)
    members = {g: np.flatnonzero(runs.groups == g) for g in groups}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(groups, size=len(groups), replace=True)
        idx = np.concatenate([members[g] for g in pick])
        v = fn(idx)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def summarize(runs: Runs, budgets, n_boot: int, boot_budgets) -> dict:
    all_idx = np.arange(len(runs.specs))
    out: dict = {}
    for m in METHODS:
        for b in budgets:
            row = {}
            for name in REPORT_STATS:
                row[name] = runs.stat(m, b, name, all_idx)
                if b in boot_budgets and name in (
                    "accuracy",
                    "false_absent_rate",
                    "inconclusive_rate",
                ):
                    row[f"{name}_ci95"] = bootstrap(
                        runs,
                        lambda idx, m=m, b=b, name=name: runs.stat(m, b, name, idx),
                        n_boot,
                        frozen.BOOT_SEED,
                    )
            out[f"{m}@{b}"] = row
    return out


def paired_differences(runs: Runs, budgets, n_boot: int) -> dict:
    all_idx = np.arange(len(runs.specs))
    out = {}
    for a, b_ in PAIRS:
        for b in budgets:
            for name in DIFF_STATS:

                def diff(idx, a=a, b_=b_, b=b, name=name):
                    va, vb = runs.stat(a, b, name, idx), runs.stat(b_, b, name, idx)
                    return None if va is None or vb is None else va - vb

                out[f"{a}-{b_}@{b}:{name}"] = {
                    "diff": diff(all_idx),
                    "ci95": bootstrap(runs, diff, n_boot, frozen.BOOT_SEED),
                }
    return out


def by_state(runs: Runs, budgets) -> dict:
    out = {}
    for state in GroundTruthState:
        idx = np.array(
            [
                i
                for i, s in enumerate(runs.specs)
                if runs.outcomes["single"][1][0][i].gt_state == state
            ]
        )
        for m in METHODS:
            for b in budgets:
                out[f"{state}:{m}@{b}"] = {
                    "n": len(idx),
                    **{
                        k: runs.stat(m, b, k, idx)
                        for k in (
                            "accuracy",
                            "false_absent_rate",
                            "false_present_rate",
                            "inconclusive_rate",
                            "avg_viewpoints",
                        )
                    },
                }
    return out


def calibration(runs: Runs, budgets) -> dict:
    return {
        f"{m}@{b}": reliability_bins([o for seed in runs.outcomes[m][b] for o in seed])
        for m in METHODS
        for b in budgets
    }


def detector_vs_success(specs, world: GazeboReplayWorld, tau_present: float) -> dict:
    """Per test frame: GT visible pixel area / detector confidence vs detection success."""
    rows = []
    for s in specs:
        if not s.layout.object_present:
            continue
        for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
            lv = world.object_visibility(s, vp)
            obs = world.observe(s, vp)
            area_px = lv.visible_px if lv is not None else 0
            rows.append((area_px, lv.vis_fraction if lv else 0.0, obs.max_confidence))
    arr = np.array(rows, dtype=float)
    area_bins = [0, 1, 500, 2000, 5000, 10000, 20000, 1e9]
    by_area = []
    for lo, hi in zip(area_bins[:-1], area_bins[1:], strict=True):
        m = (arr[:, 0] >= lo) & (arr[:, 0] < hi)
        if m.any():
            by_area.append(
                {
                    "visible_px": [lo, hi],
                    "n": int(m.sum()),
                    "detect_rate_at_tau_present": float((arr[m, 2] >= tau_present).mean()),
                    "mean_max_conf": float(arr[m, 2].mean()),
                }
            )
    conf_bins = [0, 0.05, 0.3, 0.7, 0.9, 1.0001]
    by_conf = []
    for lo, hi in zip(conf_bins[:-1], conf_bins[1:], strict=True):
        m = (arr[:, 2] >= lo) & (arr[:, 2] < hi)
        if m.any():
            by_conf.append(
                {
                    "max_conf": [lo, min(hi, 1.0)],
                    "n": int(m.sum()),
                    "mean_visible_px": float(arr[m, 0].mean()),
                    "mean_vis_fraction": float(arr[m, 1].mean()),
                }
            )
    return {"present_frames": len(arr), "by_visible_area": by_area, "by_confidence": by_conf}


def residual_failures(runs: Runs, gts, budgets=(2, 3)) -> list[dict]:
    out = []
    for b in budgets:
        for rec, o in zip(runs.records["rule"][b][0], runs.outcomes["rule"][b][0], strict=True):
            if o.correct:
                continue
            out.append(
                {
                    "budget": b,
                    "episode_id": rec.episode_id,
                    "gt_state": str(o.gt_state),
                    "expected": str(o.expected),
                    "decision": str(rec.decision),
                    "viewpoint_sequence": list(rec.viewpoint_sequence),
                    "zone_visible": [round(x.zone_visible_fraction, 3) for x in rec.observations],
                    "max_conf": [round(x.max_confidence, 4) for x in rec.observations],
                    "coverage": rec.features.get("coverage"),
                    "gt_visibility_initial": gts[rec.episode_id].visibility_initial,
                }
            )
    return out


def gate(diffs: dict, summary: dict, failures: list[dict]) -> dict:
    """Pre-registered Gate checks (decision 009 section 4)."""
    beats = {}
    for b in (2, 3):
        for other in ("random", "single"):
            ci = diffs[f"rule-{other}@{b}:accuracy"]["ci95"]
            beats[f"rule>{other}@{b}"] = bool(ci is not None and ci[0] > 0)
        beats[f"false_absent_rule<=random@{b}"] = bool(
            summary[f"rule@{b}"]["false_absent_rate"] <= summary[f"random@{b}"]["false_absent_rate"]
        )
    near = {}
    for b in frozen.FORMAL_BUDGETS:
        d = diffs[f"oracle-rule@{b}:accuracy"]
        near[b] = bool(
            d["diff"] <= 0.02 or (d["ci95"] is not None and d["ci95"][0] <= 0 <= d["ci95"][1])
        )
    return {
        "1_rule_beats_random_and_single": all(beats.values()),
        "1_detail": beats,
        "2_no_leakage": "see tests/test_leakage.py and tests/test_replay.py (CI gate)",
        "3_residual_failures": len(failures),
        "4_rule_near_oracle_per_budget": near,
        "4_rule_near_oracle": all(near.values()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.experiment")
    ap.add_argument(
        "stage", choices=["test", "dryrun"], help="dryrun = identical pipeline on the val split"
    )
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--detections", required=True)
    ap.add_argument("--renders")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=frozen.N_BOOT)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} exists: the formal test runs once (decision 009)")
    specs, gts, meta = load_episode_set(args.episodes)
    split = Split.TEST if args.stage == "test" else Split.VAL
    specs = [s for s in specs if s.split == split]
    world = GazeboReplayWorld(
        FrameStore(args.renders or meta["renders"]), DetectionCache.load(args.detections)
    )
    runs = run_all(specs, gts, world, frozen.CURVE_BUDGETS)
    summary = summarize(runs, frozen.CURVE_BUDGETS, args.n_boot, frozen.FORMAL_BUDGETS)
    diffs = paired_differences(runs, frozen.FORMAL_BUDGETS, args.n_boot)
    failures = residual_failures(runs, gts)
    import subprocess

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    )
    report = {
        "stage": args.stage,
        "git_commit": commit,
        "git_dirty": dirty,
        "split": str(split),
        "versions": frozen.VERSIONS,
        "episode_set": args.episodes,
        "image_ids": meta.get("image_ids"),
        "n_episodes": len(specs),
        "n_groups": len({s.scene_group for s in specs}),
        "formal_budgets": list(frozen.FORMAL_BUDGETS),
        "random_seeds": list(frozen.RANDOM_SEEDS),
        "n_boot": args.n_boot,
        "summary": summary,
        "paired_differences": diffs,
        "by_state": by_state(runs, frozen.FORMAL_BUDGETS),
        "calibration": calibration(runs, frozen.FORMAL_BUDGETS),
        "detector_vs_success": detector_vs_success(specs, world, frozen.DECISION_V1.tau_present),
        "residual_failures": failures,
    }
    report["gate"] = gate(diffs, summary, failures)
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    write_jsonl(
        out / "outcomes.jsonl",
        [
            {**o.__dict__, "method": m, "seed": seed}
            for m in METHODS
            for b in frozen.CURVE_BUDGETS
            for seed, outs in enumerate(runs.outcomes[m][b])
            for o in outs
        ],
    )
    print(json.dumps(report["gate"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
