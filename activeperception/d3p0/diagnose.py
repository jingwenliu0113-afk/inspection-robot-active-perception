"""Per-view and per-location diagnosis of frozen v5 (decision 037 §1). Development data only.

    uv run python -m activeperception.preflight || exit 1
    uv run python -m activeperception.d3p0.diagnose --out runs/d3p0-diag --workers 6

For every (condition, episode): the frozen v5 world observes all 13 views (its refinement is
captured), then the see-through of every view is recomputed under
T0 clean depth / true pose / no margin, T1 noisy depth / true pose / no margin,
T2 noisy depth / true pose / v5's margin; T3 is v5's own observation. Views that v5 blinds get the
counterfactual C1 (localiser pose, margin max(6 cm, 3 sigma)). Rule's budget-5 path is recorded.
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..v6.hp import fit_costs  # moved there for H-P (decision 037 appendix A)

CONDITIONS = ("D0xP0", "D3xP0", "D3xL1", "D1xL2:L1")
SEE_K = 14
_CACHE: dict = {}
_CAPTURED: dict = {}
_CURRENT: list = [None]


def _episode_set(ns: str):
    if ("specs", ns) not in _CACHE:
        from ..serialize import load_episode_set

        specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
        _CACHE[("specs", ns)] = ({s.episode_id: s for s in specs}, gts)
    return _CACHE[("specs", ns)]


def _detections(ns: str):
    if ("dets", ns) not in _CACHE:
        from ..detector.cache import DetectionCache

        _CACHE[("dets", ns)] = DetectionCache.load(f"runs/{ns}/detector-v1.jsonl")
    return _CACHE[("dets", ns)]


def _install_capture() -> None:
    """Record the RefinementV4 of the view being observed (V3World imports the function from
    ``v4.geometry`` at call time, so patching the module attribute is enough)."""
    from ..v4 import geometry as g4

    if getattr(g4, "_d3p0_patched", False):
        return
    original = g4.refine_pose_v4

    def capture(*a, **k):
        ref = original(*a, **k)
        _CAPTURED[_CURRENT[0]] = ref
        return ref

    g4.refine_pose_v4 = capture
    g4._d3p0_patched = True


def episode(args: tuple) -> dict:
    import time

    from ..v5.maclock import holder

    while holder() is not None:  # another project's heavy work started: wait, do not compete
        time.sleep(60)
    ns, eid, cond = args
    from .. import frozen_v2
    from ..framestore import FrameStore
    from ..harness import run_episode
    from ..nav.localize import map_outlines
    from ..r0b import occupied_locations
    from ..sim.replay import GazeboReplayWorld
    from ..v3.eval import (
        DecisionRuleV3,
        V3World,
        estimated_pose,
        noisy_depth,
        reported_prior,
        rule_nbv_v3,
    )
    from ..v5 import frozen_v5
    from ..v5.see import robust_visibility_v5

    _install_capture()
    specs, gts = _episode_set(ns)
    spec, gt = specs[eid], gts[eid]
    depth_level, rest = cond.split("x")
    pose_level, prior_level = (rest.split(":") + [None])[:2]
    store = FrameStore(f"renders/{ns}")
    base = GazeboReplayWorld(store, _detections(ns))
    cfg = frozen_v5.GEOMETRY
    world = V3World(base, depth_level, pose_level, cfg, True, prior_level)
    prior = reported_prior(prior_level or pose_level)
    frames = store.episode(eid)
    outlines = map_outlines(spec)
    occ = occupied_locations(spec) if spec.layout.object_present else None
    views = []
    for vp in (spec.initial_viewpoint, *spec.candidate_viewpoints):
        _CURRENT[0] = vp.id
        obs = world.observe(spec, vp)
        ref = _CAPTURED.pop(vp.id)
        d = world.diag[(eid, vp.id)]
        clean = frames.depth(vp.id)
        depth = noisy_depth(spec, vp.id, clean, depth_level)
        est = estimated_pose(spec, vp, pose_level)
        truth = vp.pose
        margin = (d["margin_xy"], d["margin_yaw"])
        t0 = robust_visibility_v5(clean, spec.camera, truth, spec.zone, 0.0, 0.0, SEE_K)
        t1 = robust_visibility_v5(depth, spec.camera, truth, spec.zone, 0.0, 0.0, SEE_K)
        t2 = robust_visibility_v5(depth, spec.camera, truth, spec.zone, *margin, SEE_K)
        fx, fy = est.x + ref.dx, est.y + ref.dy  # the fitted position, used or not
        move = math.hypot(ref.dx, ref.dy)
        along = (ref.dx * math.cos(est.yaw) + ref.dy * math.sin(est.yaw)) / move if move else 0.0
        rec = {
            "vp": vp.id,
            "status": "ok" if d["refine_ok"] else ("blind" if d["blind"] else "fallback"),
            "conflict": bool(d["conflict"]),
            "est_err": math.hypot(est.x - truth.x, est.y - truth.y),
            "fit_err": math.hypot(fx - truth.x, fy - truth.y),
            "used_err": d["err_xy"],
            "move": move,
            "move_along_axis": along,
            "dyaw": ref.dyaw,
            "scale": ref.scale,
            "spread_xy": ref.spread_xy if math.isfinite(ref.spread_xy) else None,
            "eig": ref.min_eigenvalue,
            "n_points": ref.n_points,
            "gate_xy": cfg.prior_k * prior[0],
            "margin_xy": margin[0],
            "margin_yaw": margin[1],
            "costs": fit_costs(depth, spec.camera, est, spec.zone, outlines, cfg, ref)
            if ref.n_points >= 50
            else None,
            "T0": list(t0),
            "T1": list(t1),
            "T2": list(t2),
            "T3": list(obs.location_visibility),
        }
        if d["blind"]:  # C1: trust the localiser (diagnostic counterfactual, not deployable)
            mc = (max(0.06, 3 * prior[0]), max(0.03, 3 * prior[1]))
            c1 = robust_visibility_v5(depth, spec.camera, est, spec.zone, *mc, SEE_K)
            rec["C1"] = list(c1)
            rec["C1_margin_xy"] = mc[0]
            if occ is not None:
                rec["C1_occupied_cleared"] = bool((np.asarray(c1) >= 1.0 - 1e-9)[occ].any())
        views.append(rec)
    rule = DecisionRuleV3(frozen_v2.DECISION_V2, version="decision-v3-dev")
    r5 = run_episode(spec, world, rule_nbv_v3(frozen_v5.TIE_BREAK), rule, 5, 0)
    return {
        "ns": ns,
        "episode": eid,
        "cond": cond,
        "state": gt.state.value,
        "present": bool(spec.layout.object_present),
        "rule_b5": {"views": list(r5.viewpoint_sequence), "decision": r5.decision.value},
        "views": views,
    }


def main(argv: list[str] | None = None) -> int:
    from ..preflight import problems, snapshot

    ap = argparse.ArgumentParser(prog="activeperception.d3p0.diagnose")
    ap.add_argument("--ns", default="v3-dev")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    from ..v3.eval import DEV_NAMESPACES

    if args.ns not in DEV_NAMESPACES:
        raise SystemExit(f"{args.ns}: not development data")
    bad = problems(snapshot())
    if bad:
        raise SystemExit("not starting: " + "; ".join(bad))
    specs, _ = _episode_set(args.ns)
    eids = sorted(specs)[: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for cond in args.conditions.split(","):
        path = out / f"{args.ns}-{cond.replace(':', '_')}.jsonl"
        if path.exists():
            print(f"{path} exists, skip", flush=True)
            continue
        jobs = [(args.ns, e, cond) for e in eids]
        with ProcessPoolExecutor(args.workers) as ex, open(path.with_suffix(".tmp"), "w") as f:
            for r in ex.map(episode, jobs):
                f.write(json.dumps(r) + "\n")
        path.with_suffix(".tmp").rename(path)
        print(f"{cond}: {len(jobs)} episodes -> {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
