"""Pilot checks (SPEC §9) on the Gazebo replay world. Pilot episodes never enter the
final test (decision 002); nothing here is a research result.

1. the three GT states are distinguishable (and a single view cannot tell
   ``unobservable`` from ``absent`` - the reason active perception exists)
2. teleport is deterministic (independent re-render is pixel-identical)
3. sensor timestamps / transforms are sane (stamps after teleport, depth vs ray-cast)
4. single / random / rule / oracle see the same candidate viewpoints and observations
5. the grader never swallows ``inconclusive`` (never counted as false-absent /
   false-present; correct iff decision == expected)

    python -m activeperception.pilot --episodes data/episodes/gazebo-pilot.json \\
        --frames renders/pilot --detections runs/pilot/detector-v1.jsonl \\
        --rerender renders/pilot-rerender --out results/pilot
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .decision import DECISION_RULE_VERSION, DecisionRule
from .detector.cache import DetectionCache
from .detector.evaluate import auroc
from .framestore import FrameStore
from .grader import grade
from .harness import run_episode
from .metrics import markdown_table, summarize
from .policies import OracleNBVPolicy, RandomNBVPolicy, RuleNBVPolicy, SingleViewPolicy
from .serialize import load_episode_set
from .sim.raycast import render_spec
from .sim.replay import GazeboReplayWorld
from .sim.sdf import LABEL_GROUND, LABEL_OBJECT, LABEL_PILLAR
from .types import Decision, GroundTruthState, Split

FRAME_ARRAYS = ("rgb", "depth_mm", "labels", "labels_clear")


def _all_viewpoints(spec):
    return [spec.initial_viewpoint, *spec.candidate_viewpoints]


def check_states(specs, gts, world: GazeboReplayWorld) -> dict:
    counts = Counter(str(gts[s.episode_id].state) for s in specs)
    init_conf: dict[str, list[float]] = defaultdict(list)
    init_zone: dict[str, list[float]] = defaultdict(list)
    best_conf: dict[bool, list[float]] = defaultdict(list)
    for s in specs:
        state = str(gts[s.episode_id].state)
        obs0 = world.observe(s, s.initial_viewpoint)
        init_conf[state].append(obs0.max_confidence)
        init_zone[state].append(obs0.zone_visible_fraction)
        best = max(world.observe(s, vp).max_confidence for vp in _all_viewpoints(s))
        best_conf[s.layout.object_present].append(best)
    arr = {k: np.array(v) for k, v in init_conf.items()}
    vis, unobs, absent = (
        arr.get(str(GroundTruthState.VISIBLE), np.array([])),
        arr.get(str(GroundTruthState.UNOBSERVABLE), np.array([])),
        arr.get(str(GroundTruthState.ABSENT), np.array([])),
    )
    out = {
        "counts": dict(counts),
        "initial_view": {
            k: {
                "n": len(v),
                "max_conf_mean": float(np.mean(v)),
                "max_conf_p10_p90": [float(np.quantile(v, 0.1)), float(np.quantile(v, 0.9))],
                "zone_visible_mean": float(np.mean(init_zone[k])),
            }
            for k, v in arr.items()
        },
        "auroc_initial_visible_vs_absent": auroc(vis, absent),
        "auroc_initial_visible_vs_unobservable": auroc(vis, unobs),
        "auroc_initial_unobservable_vs_absent": auroc(unobs, absent),
        "auroc_best_view_present_vs_absent": auroc(
            np.array(best_conf[True]), np.array(best_conf[False])
        ),
    }
    out["pass"] = bool(
        all(counts.get(str(st), 0) > 0 for st in GroundTruthState)
        and (out["auroc_initial_visible_vs_absent"] or 0) >= 0.95
        and (out["auroc_best_view_present_vs_absent"] or 0) >= 0.95
    )
    return out


def check_determinism(store_a: FrameStore, store_b: FrameStore, episode_ids) -> dict:
    per_array = {k: [0, 0] for k in FRAME_ARRAYS}  # identical, compared
    mismatches = []
    for eid in episode_ids:
        a = np.load(store_a.path(eid))
        b = np.load(store_b.path(eid))
        for k in FRAME_ARRAYS:
            if k not in a.files and k not in b.files:
                continue
            per_array[k][1] += 1
            if k in a.files and k in b.files and np.array_equal(a[k], b[k]):
                per_array[k][0] += 1
            else:
                mismatches.append((eid, k))
    return {
        "episodes": len(episode_ids),
        "identical_over_compared": {k: f"{v[0]}/{v[1]}" for k, v in per_array.items()},
        "mismatches": mismatches,
        "pass": not mismatches and len(episode_ids) > 0,
    }


def check_timestamps(store: FrameStore, specs) -> dict:
    problems = []
    gaps = []
    for s in specs:
        npz = np.load(store.path(s.episode_id))
        meta = store.episode(s.episode_id).meta
        stamps, t_ref = npz["stamps_ns"], npz["t_ref_ns"]
        gaps.extend(((stamps - t_ref) / 1e9).tolist())
        if not (stamps - t_ref >= meta["settle_ns"]).all():
            problems.append((s.episode_id, "frame not newer than teleport + settle"))
        if not (np.diff(stamps) > 0).all():
            problems.append((s.episode_id, "full-pass stamps not increasing"))
        if "stamps_clear_ns" in npz.files:
            clear, t_ref_c = npz["stamps_clear_ns"], npz["t_ref_clear_ns"]
            if not ((clear - t_ref_c >= meta["settle_ns"]).all() and clear[0] > stamps[-1]):
                problems.append((s.episode_id, "clear-pass stamps out of order"))
        poses = npz["poses"]
        expected = np.array(
            [[v.pose.x, v.pose.y, v.pose.z, v.pose.yaw, v.pose.pitch] for v in _all_viewpoints(s)]
        )
        if not np.allclose(poses, expected, atol=1e-12):
            problems.append((s.episode_id, "recorded poses differ from spec"))
    return {
        "frames": len(gaps),
        "stamp_minus_teleport_s": [float(np.min(gaps)), float(np.max(gaps))],
        "problems": problems,
        "pass": not problems,
    }


def check_transform(store: FrameStore, specs, proxy_radius: float, every: int = 4) -> dict:
    errs, agree = [], []
    for s in specs:
        fr = store.episode(s.episode_id)
        for vp in _all_viewpoints(s)[::every]:
            gz_d, gz_l = fr.depth(vp.id), fr.labels(vp.id)
            rc_d, rc_l = render_spec(s, vp.pose, proxy_radius)
            static = (gz_l == LABEL_PILLAR) | (gz_l == LABEL_GROUND)
            m = static & (rc_l == gz_l) & np.isfinite(gz_d) & np.isfinite(rc_d)
            errs.append(np.abs(gz_d[m] - rc_d[m]))
            non_obj = (gz_l != LABEL_OBJECT) & (rc_l != LABEL_OBJECT)
            agree.append(float((gz_l[non_obj] == rc_l[non_obj]).mean()))
    e = np.concatenate(errs)
    out = {
        "depth_kind": "planar",
        "views": len(agree),
        "depth_abs_err_m": {
            "median": float(np.median(e)),
            "p99": float(np.percentile(e, 99)),
            "max": float(e.max()),
        },
        "label_agreement_non_object_min": float(min(agree)),
        "label_agreement_non_object_mean": float(np.mean(agree)),
    }
    out["pass"] = bool(
        out["depth_abs_err_m"]["median"] < 0.002
        and out["depth_abs_err_m"]["p99"] < 0.01
        and out["label_agreement_non_object_min"] > 0.99
    )
    return out


def run_policies(specs, gts, world, rule, budgets, run_seed: int = 0):
    policies = {
        "single": SingleViewPolicy(),
        "random": RandomNBVPolicy(),
        "rule": RuleNBVPolicy(),
        "oracle": OracleNBVPolicy(lambda e: gts[e]),
    }
    records = {}
    for b in budgets:
        for name, pol in policies.items():
            records[(name, b)] = [run_episode(s, world, pol, rule, b, run_seed) for s in specs]
    return records


def check_same_candidates(specs, records) -> dict:
    by_id = {s.episode_id: s for s in specs}
    problems = []
    seen: dict[tuple[str, int], object] = {}
    for (name, budget), recs in records.items():
        for r in recs:
            cand = {vp.id for vp in by_id[r.episode_id].candidate_viewpoints}
            if r.viewpoint_sequence[0] != by_id[r.episode_id].initial_viewpoint.id:
                problems.append((name, budget, r.episode_id, "initial view not first"))
            if not set(r.viewpoint_sequence[1:]) <= cand:
                problems.append((name, budget, r.episode_id, "visited a non-candidate"))
            for o in r.observations:
                key = (r.episode_id, o.viewpoint_id)
                if key in seen and seen[key] != o:
                    problems.append((name, budget, r.episode_id, f"observation differs at {key}"))
                seen.setdefault(key, o)
    b1 = [k for k in records if k[1] == 1]
    if b1:
        ref = [(r.decision, r.viewpoint_sequence) for r in records[b1[0]]]
        for k in b1[1:]:
            if [(r.decision, r.viewpoint_sequence) for r in records[k]] != ref:
                problems.append((k[0], 1, "-", "budget 1 differs from single view"))
    return {"observations_compared": len(seen), "problems": problems, "pass": not problems}


def check_grader(specs, gts, records) -> dict:
    by_id = {s.episode_id: s for s in specs}
    violations = []
    confusion: dict[str, dict[str, int]] = {}
    for (name, budget), recs in records.items():
        cm: Counter = Counter()
        for r in recs:
            o = grade(r, gts[r.episode_id], by_id[r.episode_id])
            cm[f"{o.expected}->{o.decision}"] += 1
            if o.inconclusive and (o.false_absent or o.false_present):
                violations.append((name, budget, r.episode_id, "inconclusive counted as error"))
            if o.correct != (o.decision == o.expected):
                violations.append((name, budget, r.episode_id, "correct != (decision == expected)"))
            if o.inconclusive != (o.decision == Decision.INCONCLUSIVE):
                violations.append((name, budget, r.episode_id, "inconclusive flag wrong"))
        confusion[f"{name}@{budget}"] = dict(sorted(cm.items()))
    return {"confusion": confusion, "violations": violations, "pass": not violations}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.pilot")
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--detections", required=True)
    ap.add_argument("--rerender", help="independent re-render of the same specs")
    ap.add_argument("--budgets", default="1,3,5")
    ap.add_argument("--proxy-radius", type=float, default=0.15)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    specs, gts, meta = load_episode_set(args.episodes)
    if {s.split for s in specs} != {Split.PILOT}:
        raise SystemExit("pilot checks only run on the pilot split")
    store = FrameStore(args.frames)
    cache = DetectionCache.load(args.detections)
    world = GazeboReplayWorld(store, cache)
    rule = DecisionRule()
    budgets = [int(b) for b in args.budgets.split(",")]
    report: dict = {
        "episode_set": args.episodes,
        "image_ids": meta.get("image_ids"),
        "detector": cache.detector,
        "decision_rule": DECISION_RULE_VERSION,
        "note": "pilot only - not a research result; pilot episodes never enter the final test",
    }
    report["1_states"] = check_states(specs, gts, world)
    if args.rerender:
        ids = [s.episode_id for s in specs]
        report["2_determinism"] = check_determinism(store, FrameStore(args.rerender), ids)
    report["3a_timestamps"] = check_timestamps(store, specs)
    report["3b_transform"] = check_transform(store, specs, args.proxy_radius)
    records = run_policies(specs, gts, world, rule, budgets)
    report["4_same_candidates"] = check_same_candidates(specs, records)
    report["5_grader"] = check_grader(specs, gts, records)
    by_id = {s.episode_id: s for s in specs}
    summaries = {
        key: summarize([grade(r, gts[r.episode_id], by_id[r.episode_id]) for r in recs])
        for key, recs in records.items()
    }
    report["sweep_table"] = markdown_table(summaries)
    report["all_pass"] = all(
        v["pass"] for k, v in report.items() if isinstance(v, dict) and "pass" in v
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pilot_report.json").write_text(json.dumps(report, indent=1, default=str))
    checks = {k: v.get("pass") for k, v in report.items() if isinstance(v, dict)}
    print(json.dumps(checks, indent=1))
    print(report["sweep_table"])
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
