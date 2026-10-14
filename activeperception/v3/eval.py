"""v3 development harness (decision 024): R0b's error models x v3 components, with ablations.

    uv run python -m activeperception.v3.eval --ns v3-dev --configs v2,see,pose,full \\
        --conditions D0xP0,D1xL1,D2xL2 --out runs/v3-dev/geometry

Development data only. Each (condition, config) replays the four methods through the Core
harness on a ``V3World``: the R0b depth / pose errors (``r0b_noise``, unchanged) are applied,
then the v3 geometry (``v3.geometry``) and, optionally, zone gating of detections
(``decision-v3``). Ground truth (object position, true poses) is used for scoring only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .. import frozen_v2
from ..decision import DecisionRuleV2
from ..r0b import DEPTH_LEVELS, POSE_LEVELS, occupied_locations
from ..r0b_noise import apply_depth_noise, perturb_pose, rng_for
from ..sensing import cleared_locations
from ..types import Decision, DecisionOutput, Observation
from .geometry import (
    V2_GEOMETRY,
    GeometryConfig,
    blind,
    margin_for,
    refine_pose_v3,
    robust_visibility_v3,
)

CONFIGS = {
    "v2": V2_GEOMETRY,  # decision 016 exactly
    "see": dataclasses.replace(V2_GEOMETRY, see_v3=True, name="see"),  # + see-through-v3
    "pose": GeometryConfig(name="pose"),  # + weighted / range-cut / scale refinement
    "pose-e5": GeometryConfig(min_eigenvalue=5.0, name="pose-e5"),
    "m4": GeometryConfig(margin_ok=(0.04, 0.02), name="m4"),
    "m8": GeometryConfig(margin_ok=(0.08, 0.04), name="m8"),
    "m4-e5": GeometryConfig(min_eigenvalue=5.0, margin_ok=(0.04, 0.02), name="m4-e5"),
    "m4p": GeometryConfig(margin_ok=(0.04, 0.02), prior_k=3.0, name="m4p"),
    "m6p": GeometryConfig(margin_ok=(0.06, 0.03), prior_k=3.0, name="m6p"),
    # the fit contradicts the localiser -> trust neither (dev: localiser over-confident 2x)
    "m6c": GeometryConfig(margin_ok=(0.06, 0.03), prior_k=3.0, on_conflict="blind", name="m6c"),
    "m6b": GeometryConfig(  # ... and any failed fit
        margin_ok=(0.06, 0.03),
        prior_k=3.0,
        on_conflict="blind",
        on_degenerate="blind",
        name="m6b",
    ),
}


def config(name: str) -> GeometryConfig:
    if name == "v3":  # the frozen one (decision 025)
        from .frozen_v3 import GEOMETRY

        return GEOMETRY
    return CONFIGS[name]


PRIOR_FLOOR = (0.01, 0.005)  # the covariance a localiser reports even when it is exact


def reported_prior(pose_level: str) -> tuple[float, float]:
    """The localiser's own covariance (AMCL publishes it): here the error model's sigma."""
    pn = POSE_LEVELS[pose_level]
    if pn is None:
        return PRIOR_FLOOR
    return max(pn.sigma_xy, PRIOR_FLOOR[0]), max(pn.sigma_yaw, PRIOR_FLOOR[1])


DEV_NAMESPACES = ("v3-dev", "v3-dev-dx", "r0b-dev", "nav-b1")  # decision 024 §3
ZONE_SLACK_M = 0.25  # a detection counts as in the zone up to this far outside its rim
GATE_MIN_VALID = 0.3


# ---------------------------------------------------------------- decision-v3: zone gating


def locate_detection(det, depth: np.ndarray, camera, pose) -> tuple[float, float] | None:
    """Ground position (x, y) of a detection: median depth of the box's central half, ray
    through the box centre. None when the box has too few valid depth pixels."""
    from ..geometry import rotation_matrix

    x1, y1, x2, y2 = det.bbox
    w, h = x2 - x1, y2 - y1
    u1, u2 = int(max(0, x1 + w / 4)), int(min(camera.width, x2 - w / 4 + 1))
    v1, v2 = int(max(0, y1 + h / 4)), int(min(camera.height, y2 - h / 4 + 1))
    patch = depth[v1:v2, u1:u2].astype(float)
    ok = np.isfinite(patch) & (patch > 0)
    if patch.size == 0 or ok.mean() < GATE_MIN_VALID:
        return None
    d = float(np.median(patch[ok]))
    u, v = (x1 + x2) / 2, (y1 + y2) / 2
    f = camera.focal_px
    cam = np.array([d, -(u - camera.width / 2) / f * d, -(v - camera.height / 2) / f * d])
    p = cam @ rotation_matrix(pose.yaw, pose.pitch).T + np.array(pose.position())
    return float(p[0]), float(p[1])


def gate(dets, depth, camera, pose, zone, slack: float = ZONE_SLACK_M) -> dict:
    """c_in: max confidence of detections located in the zone (may make 'present');
    c_block: max over in-zone and unlocatable detections (may block 'absent')."""
    c_in = c_block = 0.0
    flags = []
    for det in dets:
        xy = locate_detection(det, depth, camera, pose)
        if xy is None:
            flags.append("unknown")
            c_block = max(c_block, det.confidence)
        elif math.hypot(xy[0] - zone.cx, xy[1] - zone.cy) <= zone.radius + slack:
            flags.append("in")
            c_in = max(c_in, det.confidence)
            c_block = max(c_block, det.confidence)
        else:
            flags.append("out")
    return {"c_in": c_in, "c_block": c_block, "flags": flags}


class DecisionRuleV3(DecisionRuleV2):
    """decision-v2 thresholds; 'present' from in-zone detections only, 'absent' blocked by any
    in-zone or unlocatable detection. Without gate data it is exactly decision-v2."""

    def decide(self, episode, history) -> DecisionOutput:
        if not all("c_in" in o.meta for o in history):
            return super().decide(episode, history)
        p = self.params
        c_in = max(o.meta["c_in"] for o in history)
        c_block = max(o.meta["c_block"] for o in history)
        cleared = self.cleared_fraction(history)
        feats = {
            "max_confidence": c_in,
            "cleared_fraction": cleared,
            "n_views": float(len(history)),
        }
        if c_in >= p.tau_present:
            return DecisionOutput(Decision.PRESENT, confidence=c_in, features=feats)
        if cleared >= p.tau_clear - 1e-9 and c_block < p.tau_absent:
            return DecisionOutput(
                Decision.ABSENT, confidence=cleared * (1.0 - c_block), features=feats
            )
        return DecisionOutput(Decision.INCONCLUSIVE, confidence=0.0, features=feats)


def rule_nbv_v3(tie_break: bool):
    """rule-nbv-v2 with a tiny novelty weight: it only separates exact ties (v2 picked the lowest
    candidate id), since one location of visibility gain is worth 1/64 = 0.016."""
    from ..policies.rule_nbv_v2 import RuleNBVv2Policy

    params = dataclasses.replace(frozen_v2.RULE_NBV_V2, w_novelty=1e-3 if tie_break else 0.0)
    return RuleNBVv2Policy(params, frozen_v2.DECISION_V2, version="rule-nbv-v3-dev")


# ---------------------------------------------------------------- world


class V3World:
    name = "gazebo-v3"

    def __init__(
        self, base, depth_level, pose_level, cfg: GeometryConfig, gated: bool, prior_level=None
    ):
        self.base, self.cfg, self.gated = base, cfg, gated
        self.depth_level, self.pose_level = depth_level, pose_level
        self.prior_level = prior_level or pose_level  # what the localiser claims its error is
        self._cache: dict = {}
        self.diag: dict = {}

    def observe(self, spec, viewpoint) -> Observation:
        from ..nav.localize import map_outlines
        from ..nav.observe import observation, observation_d016

        key = (spec.episode_id, viewpoint.id)
        if key in self._cache:
            return self._cache[key]
        self.base.zone_visible_fraction(spec, viewpoint)  # digest + rendered pose checks
        depth = self.base._frames(spec).depth(viewpoint.id)
        view = f"v{viewpoint.id}"
        dn, pn = DEPTH_LEVELS.get(self.depth_level), POSE_LEVELS[self.pose_level]
        if self.depth_level == "D3":  # decision 028 §5, development only
            from ..depthnoise.d3 import apply_d3

            f = spec.camera.width / 2 / math.tan(spec.camera.hfov / 2)
            depth = apply_d3(depth, f, rng_for(spec.episode_id, view, "depth", "D3"))
        elif dn is not None:
            depth = apply_depth_noise(depth, dn, rng_for(spec.episode_id, view, "depth", dn.name))
        est = viewpoint.pose
        if pn is not None:
            est = perturb_pose(viewpoint.pose, pn, rng_for(spec.episode_id, view, "pose", pn.name))
        dets = self.base.detections.get(spec.episode_id, viewpoint.id)
        spread = (math.nan, math.nan)
        conflict = blinded = False
        if self.cfg == V2_GEOMETRY:  # exactly decision 016 (R0b pipeline b)
            obs, ref = observation_d016(spec, viewpoint.id, depth, dets, est)
            ok, margin = ref.ok, (None, None)
        else:
            prior = reported_prior(self.prior_level)
            ref = refine_pose_v3(
                depth, spec.camera, est, spec.zone, map_outlines(spec), self.cfg, prior=prior
            )
            margin = margin_for(ref, self.cfg, prior)
            vis = robust_visibility_v3(
                depth, spec.camera, ref.pose, spec.zone, *margin, self.cfg.see_v3
            )
            conflict, blinded = ref.conflict, blind(ref, self.cfg)
            if blinded:
                vis = (0.0,) * len(vis)
            obs = dataclasses.replace(
                observation(spec, viewpoint.id, depth, dets, ref.pose), location_visibility=vis
            )
            ok, spread = ref.ok, (ref.spread_xy, ref.spread_yaw)
        used, true = obs.viewpoint.pose, viewpoint.pose
        g = None
        if self.gated:
            g = gate(dets, depth, spec.camera, used, spec.zone)
            obs = dataclasses.replace(
                obs, meta={**obs.meta, "c_in": g["c_in"], "c_block": g["c_block"]}
            )
        seen = np.asarray(obs.location_visibility) >= frozen_v2.DECISION_V2.col_min - 1e-9
        self.diag[key] = {  # scoring only
            "occupied_cleared": bool((seen & occupied_locations(spec)).any()),
            "err_xy": math.hypot(used.x - true.x, used.y - true.y),
            "err_yaw": abs((used.yaw - true.yaw + math.pi) % (2 * math.pi) - math.pi),
            "refine_ok": bool(ok),
            "conflict": conflict,
            "blind": blinded,
            "spread_xy": spread[0],
            "spread_yaw": spread[1],
            "margin_xy": margin[0],
            "margin_yaw": margin[1],
            "gate": None if g is None else g["flags"],
            "max_conf": max((d.confidence for d in dets), default=0.0),
        }
        self._cache[key] = obs
        return obs


# ---------------------------------------------------------------- outcomes


def outcomes(specs, gts, world, rule, tie_break: bool) -> dict:
    from ..grader import grade
    from ..harness import run_episode
    from ..nav.b1_analysis import BUDGETS, JOBS, _outcome
    from ..policies import OracleNBVv2Policy, RandomNBVPolicy, SingleViewPolicy
    from ..sim.replay import make_peek

    peek = make_peek(world, specs)
    out = {}
    for method, seed in JOBS:
        for b in BUDGETS:
            if method == "single":
                pol = SingleViewPolicy()
            elif method == "random":
                pol = RandomNBVPolicy()
            elif method == "rule":
                pol = rule_nbv_v3(tie_break)
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


def run(job: tuple) -> dict:
    ns, depth_level, pose_level, cfg_name, gated, tie_break, *rest = job
    prior_level = rest[0] if rest else None
    detections = rest[1] if len(rest) > 1 else f"runs/{ns}/detector-v1.jsonl"  # detector-v2: T4
    from ..detector.cache import DetectionCache
    from ..framestore import FrameStore
    from ..nav.b1_analysis import summarize
    from ..serialize import load_episode_set
    from ..sim.replay import GazeboReplayWorld

    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    base = GazeboReplayWorld(FrameStore(f"renders/{ns}"), DetectionCache.load(detections))
    world = V3World(base, depth_level, pose_level, config(cfg_name), gated, prior_level)
    rule = DecisionRuleV3(frozen_v2.DECISION_V2, version="decision-v3-dev")
    res = outcomes(specs, gts, world, rule, tie_break)
    all_views = []
    for s in specs:
        hist = [world.observe(s, vp) for vp in (s.initial_viewpoint, *s.candidate_viewpoints)]
        if s.layout.object_present and cleared_locations(hist, 1.0).all():
            all_views.append(s.episode_id)
    d = world.diag
    present = [v for (e, _), v in d.items() if gts[e].object_present]
    per_episode = {  # Rule's decision per budget, for the failure / occlusion analysis
        s.episode_id: {
            "state": gts[s.episode_id].state.value,
            **{f"b{b}": res[("rule", 0, b, s.episode_id)]["decision"] for b in (2, 3, 5)},
        }
        for s in specs
    }
    job = {"depth": depth_level, "pose": pose_level, "config": cfg_name}
    if prior_level:
        job["prior"] = prior_level
    occ = {"views": sum(v["occupied_cleared"] for v in present), "present_views": len(present)}
    return {
        "job": job | {"gated": gated, "tie_break": tie_break},
        "summary": summarize(res, specs, gts),
        "all_views_geometric_risk": all_views,
        "occupied_false_clearance": occ,
        "views": [dict(x) | {"episode": e, "vp": i} for (e, i), x in d.items()],
        "rule_per_episode": per_episode,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v3.eval")
    ap.add_argument("--ns", default="v3-dev")
    ap.add_argument("--configs", default="v2,see,pose,full")
    ap.add_argument("--conditions", default="D0xP0,D1xL1,D2xL2")
    ap.add_argument("--gated", default="0")
    ap.add_argument("--tie-break", default="0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--prior", default="", help="pose level the localiser reports (mismatch)")
    args = ap.parse_args(argv)
    if args.ns not in DEV_NAMESPACES:  # formal sets run only through v3.formal (decision 025)
        raise SystemExit(f"{args.ns}: not development data (allowed: {DEV_NAMESPACES})")
    jobs = [
        (args.ns, *c.split("x"), cfg, g == "1", t == "1", args.prior or None)
        for c in args.conditions.split(",")
        for cfg in args.configs.split(",")
        for g in args.gated.split(",")
        for t in args.tie_break.split(",")
    ]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(min(args.workers, len(jobs))) as ex:
        for r in ex.map(run, jobs):
            j = r["job"]
            name = (
                f"{j['depth']}x{j['pose']}-{j['config']}-g{int(j['gated'])}-t{int(j['tie_break'])}"
            ) + (f"-pr{j['prior']}" if j.get("prior") else "")
            (out / f"{name}.json").write_text(json.dumps(r) + "\n")
            s, occ = r["summary"], r["occupied_false_clearance"]
            fa = sum(v["false_absent"] for v in s.values())
            fp = sum(v["false_present"] for v in s.values())
            gr = sum(v["geometric_risk"] for v in s.values())
            e = np.array([v["err_xy"] for v in r["views"]])
            print(
                f"{name}: FA {fa} FP {fp} GR {gr} allview {len(r['all_views_geometric_risk'])} "
                f"occ {occ['views']}/{occ['present_views']} "
                f"| rule b2 {s['rule@2']['accuracy']:.3f} "
                f"b3 {s['rule@3']['accuracy']:.3f} b5 {s['rule@5']['accuracy']:.3f} "
                f"absent@5 {s['rule@5']['accuracy_by_state']['absent']:.3f} "
                f"| err p95 {np.quantile(e, 0.95) * 100:.1f} cm",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
