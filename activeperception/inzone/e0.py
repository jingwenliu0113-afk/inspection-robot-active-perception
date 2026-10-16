"""E0 (decision 036 appendix A): method, metric and feasibility checks on existing dev data.

    uv run python -m activeperception.preflight || exit 1
    uv run --extra detectors python -m activeperception.inzone.e0 --out results/inzone-e0

Development data only (``data/detv2/dev.csv``, ``v3-dev``, ``v3-dev-dx``). No image transform is
used as multi-view evidence. detector-v1 and detector-v2 (``runs/detv2/base``) run under the same
conditions: same images, same preprocessing, CPU, frozen thresholds (present 0.7, absent 0.02).
Ground truth (object positions, visibility) only groups and filters views for the analysis.
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .. import r0a
from . import metrics as m

TAU = r0a.TAU_PRESENT
TAU_HIS = (0.95, 0.98, 0.99)
MIN_SEP = math.radians(45.0)
VISIBLE_MIN = 0.5
ASSIGN_M = 0.6  # a located detection belongs to the nearest object within this distance
DEV_MANIFEST = Path("data/detv2/dev.csv")
REAL_CACHES = {"v1": Path("runs/detv2/dev-v1.jsonl"), "v2": Path("runs/detv2/base/dev.jsonl")}
V2_WEIGHTS = "runs/detv2/base/weights.pth"


def sim_caches(ns: str) -> dict[str, Path]:
    v2 = Path("runs/detv2/base") / f"{ns}.jsonl"
    return {"v1": Path(f"runs/{ns}/detector-v1.jsonl"), "v2": v2}


# ---------------------------------------------------------------- E0-1 reproducibility


def reproducibility(n: int = 20, seed: int = 0) -> dict:
    from ..detector.cache import DetectionCache
    from ..detv2 import evaluate as ev
    from ..detv2.data import image_path
    from ..framestore import FrameStore

    rng = np.random.default_rng(seed)
    rows = r0a.read_csv(DEV_MANIFEST)
    pick = [rows[i] for i in rng.choice(len(rows), n, replace=False)]
    store = FrameStore("renders/v3-dev")
    keys = DetectionCache.load(sim_caches("v3-dev")["v1"]).keys()
    frames = [keys[i] for i in rng.choice(len(keys), n, replace=False)]
    out = {}
    for name, weights in (("v1", None), ("v2", V2_WEIGHTS)):
        det = ev.detector(weights, "cpu")
        recs = ev.load(REAL_CACHES[name])
        d_real = []
        for row in pick:
            rgb, _ = r0a.load_rgb(image_path(Path("data/raw/detv2"), row))
            dets = det.detect(r0a.camera_equivalent(rgb))
            top = dets[0][0] if dets else 0.0
            cached = recs[f"{row['source']}:{row['image_id']}"]["detections"]
            d_real.append(abs(top - (cached[0][0] if cached else 0.0)))
        cache = DetectionCache.load(sim_caches("v3-dev")[name])
        d_sim = []
        for eid, vid in frames:
            dets = det.detect(store.episode(eid).rgb(vid))
            raw = cache.raw(eid, vid)
            d_sim.append(abs((dets[0][0] if dets else 0.0) - (raw[0][0] if raw else 0.0)))
        out[name] = {"real_max_abs_diff": max(d_real), "sim_max_abs_diff": max(d_sim)}
    out["pass"] = all(v["real_max_abs_diff"] <= 1e-3 and v["sim_max_abs_diff"] <= 1e-3
                      for k, v in out.items() if k != "pass")  # fmt: skip
    out["n_each"] = n
    return out


# ---------------------------------------------------------------- E0-2 real-photo bands


def real_bands() -> dict:
    from ..detv2 import evaluate as ev

    rows = r0a.read_csv(DEV_MANIFEST)
    out = {}
    for name, path in REAL_CACHES.items():
        recs = ev.load(path)
        missing = 0
        groups: dict[str, list[float]] = {}
        for row in rows:
            rec = recs.get(f"{row['source']}:{row['image_id']}")
            if rec is None:
                missing += 1
                continue
            c = rec["detections"][0][0] if rec["detections"] else 0.0
            g = ev.group_of(row)
            groups.setdefault(g, []).append(c)
            if row["label"] == "neg":
                groups.setdefault("neg:all", []).append(c)
            else:
                groups.setdefault("pos:all", []).append(c)
        if missing:
            raise SystemExit(f"{path}: {missing} dev images without a cached detection")
        res = {"n": {g: len(v) for g, v in groups.items()}, "bands": {}}
        for g in ("neg:verified", "neg:all", "pos:all", "pos:boxed", "pos:image-level"):
            res["bands"][g] = m.bands(groups[g])
        res["fp_rate_at_tau"] = {
            g: r0a.rate(sum(c >= TAU for c in groups[g]), len(groups[g]))
            for g in ("neg:verified", "neg:all")
        }
        res["h2_ceiling"] = {
            f"{t}": {g: m.h2_ceiling(groups[g], TAU, t) for g in ("neg:verified", "neg:all")}
            for t in TAU_HIS
        }
        res["recall_exposure"] = {
            f"{t}": m.recall_exposure(groups["pos:all"], TAU, t) for t in TAU_HIS
        }
        res["present_rate_pos"] = r0a.rate(
            sum(c >= TAU for c in groups["pos:all"]), len(groups["pos:all"])
        )
        res["lookalike_fp_by_category"] = {
            g.split(":", 1)[1]: sum(c >= TAU for c in v)
            for g, v in groups.items()
            if g.startswith("neg:") and g not in ("neg:verified", "neg:all")
        }  # fmt: skip
        out[name] = res
    return out


# ---------------------------------------------------------------- E0-3 simulated multi-view


def _views(spec, gt):
    vps = (spec.initial_viewpoint, *spec.candidate_viewpoints)
    vis = {spec.initial_viewpoint.id: gt.visibility_initial, **gt.visibility_by_viewpoint}
    return [(vp.id, vp.azimuth, vis.get(vp.id, 0.0)) for vp in vps]


def sim_consistency(ns: str = "v3-dev") -> dict:
    from ..detector.cache import DetectionCache
    from ..serialize import load_episode_set

    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    out = {}
    for name, path in sim_caches(ns).items():
        cache = DetectionCache.load(path)

        def conf(eid, vid, cache=cache):
            raw = cache.raw(eid, vid)
            return raw[0][0] if raw else 0.0

        by_group: dict[int, list[tuple[int, int]]] = {}
        all_views = []
        visible_conf, absent_conf = [], []
        for s in specs:
            g = gts[s.episode_id]
            views = _views(s, g)
            if not g.object_present:
                absent_conf += [conf(s.episode_id, v) for v, _, _ in views]
                continue
            vis = [(conf(s.episode_id, v), a) for v, a, sc in views if sc >= VISIBLE_MIN]
            visible_conf += [c for c, _ in vis]
            if vis:
                c, a = zip(*vis, strict=True)
                by_group.setdefault(s.scene_group, []).append(m.pair_counts(c, a, TAU, MIN_SEP))
            c_all = [conf(s.episode_id, v) for v, _, _ in views]
            a_all = [a for _, a, _ in views]
            all_views.append(m.pair_counts(c_all, a_all, TAU, MIN_SEP))
        dens = [sum(p[0] for p in v) for v in by_group.values()]
        nums = [sum(p[1] for p in v) for v in by_group.values()]
        p = sum(nums) / sum(dens) if sum(dens) else None
        out[name] = {
            "visible_pairs_i": int(sum(dens)),
            "visible_pairs_ij": int(sum(nums)),
            "p_j_given_i_visible": p,
            "ci95_scene_group": m.cluster_bootstrap_ratio(nums, dens),
            "p_j_given_i_all_views": (
                sum(x[1] for x in all_views) / max(1, sum(x[0] for x in all_views))
            ),
            "visible_views": len(visible_conf),
            "visible_present": r0a.rate(sum(c >= TAU for c in visible_conf), len(visible_conf)),
            "visible_needs_confirmation_0.98": m.recall_exposure(visible_conf, TAU, 0.98),
            "absent_views": len(absent_conf),
            "absent_false_present": int(sum(c >= TAU for c in absent_conf)),
            "absent_blocked": int(sum(c >= r0a.TAU_ABSENT for c in absent_conf)),
        }
    return out


# ---------------------------------------------------------------- E0-4 location consistency


CONDITIONS = (("D0", "P0"), ("D1", "L1"), ("D3", "L1"))


def _locate_episode(args: tuple) -> dict:
    ns, eid, detector = args
    from ..detector.cache import DetectionCache
    from ..framestore import FrameStore
    from ..serialize import load_episode_set
    from ..v3.eval import estimated_pose, locate_detection, noisy_depth

    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    spec = next(s for s in specs if s.episode_id == eid)
    cache = DetectionCache.load(sim_caches(ns)[detector])
    frames = FrameStore(f"renders/{ns}").episode(eid)
    objects = []
    if spec.layout.object_present and spec.layout.object_pose is not None:
        objects.append(("target", spec.layout.object_pose))
    objects += [(f"distractor{k}", p) for k, p in enumerate(spec.layout.distractors)]
    out = {f"{d}x{p}": {} for d, p in CONDITIONS}
    for vp in (spec.initial_viewpoint, *spec.candidate_viewpoints):
        dets = [d for d in cache.get(eid, vp.id) if d.confidence >= TAU]
        if not dets:
            continue
        clean = frames.depth(vp.id)
        for d_level, p_level in CONDITIONS:
            depth = noisy_depth(spec, vp.id, clean, d_level)
            pose = estimated_pose(spec, vp, p_level)
            for det in dets:
                xy = locate_detection(det, depth, spec.camera, pose)
                if xy is None:
                    continue
                dist = [(math.hypot(xy[0] - o.x, xy[1] - o.y), name) for name, o in objects]
                if not dist:
                    continue
                e, name = min(dist)
                if e <= ASSIGN_M:
                    out[f"{d_level}x{p_level}"].setdefault(name, []).append([xy[0], xy[1], e])
    return {"episode": eid, "located": out}


def location_consistency(workers: int = 4) -> dict:
    from ..serialize import load_episode_set

    jobs = []
    for ns in ("v3-dev", "v3-dev-dx"):
        specs, _, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
        for s in specs:
            if s.layout.object_present or s.layout.distractors:
                jobs += [(ns, s.episode_id, d) for d in ("v1", "v2")]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_locate_episode, jobs))
    out = {}
    for det in ("v1", "v2"):
        for ns in ("v3-dev", "v3-dev-dx"):
            for cond in (f"{d}x{p}" for d, p in CONDITIONS):
                pair_d, err = {"target": [], "distractor": []}, {"target": [], "distractor": []}
                for (jns, _, jd), r in zip(jobs, res, strict=True):
                    if jns != ns or jd != det:
                        continue
                    for name, pts in r["located"][cond].items():
                        kind = "target" if name == "target" else "distractor"
                        pair_d[kind] += m.spread([(x, y) for x, y, _ in pts])
                        err[kind] += [e for _, _, e in pts]
                out[f"{det}:{ns}:{cond}"] = {
                    k: {"pairwise": m.summarize_distances(pair_d[k]),
                        "to_truth": m.summarize_distances(err[k])}
                    for k in ("target", "distractor") if err[k]
                }  # fmt: skip
    return out


# ---------------------------------------------------------------- E0-5 exposure model


def exposure_table(real: dict) -> dict:
    out = {}
    for name, res in real.items():
        p = res["fp_rate_at_tau"]["neg:verified"]["rate"]
        out[name] = {"p_per_view": p, **{f"k={k}": m.exposure(p, k) for k in range(1, 6)}}
    return out


# ---------------------------------------------------------------- main


def ensure_v2_cache(ns: str) -> None:
    from ..detv2.formal import sim_cache

    sim_cache(f"renders/{ns}", V2_WEIGHTS, sim_caches(ns)["v2"])


def main(argv: list[str] | None = None) -> int:
    from ..preflight import problems, snapshot

    ap = argparse.ArgumentParser(prog="activeperception.inzone.e0")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-repro", action="store_true")
    args = ap.parse_args(argv)
    bad = problems(snapshot())
    if bad:
        raise SystemExit("not starting: " + "; ".join(bad))
    ensure_v2_cache("v3-dev-dx")  # same function and device as the v3-dev cache (CPU)
    report = {"protocol": "decision 036 appendix A (E0)", "tau": TAU, "tau_his": TAU_HIS}
    report["E0-1"] = None if args.skip_repro else reproducibility()
    report["E0-2"] = real_bands()
    report["E0-3"] = {
        "v3-dev": sim_consistency("v3-dev"),
        "v3-dev-dx": sim_consistency("v3-dev-dx"),
    }
    report["E0-4"] = location_consistency(args.workers)
    report["E0-5"] = exposure_table(report["E0-2"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "e0.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: (v.get("pass") if isinstance(v, dict) else v) for k, v in report.items()
                      if k.startswith("E0-1")}, indent=1))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
