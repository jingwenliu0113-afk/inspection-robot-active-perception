"""Depth-scale self-calibration from earlier inspection rounds (decision 033, development).

A depth camera's scale error is mostly fixed to the camera (R0b D1 +1 %, D2 +2 %, D3 -2.5 % plus a
1 % frame-to-frame jitter; the real D435 under-estimates range by up to 2.5 %, decision 028).
Frozen v4 tries depth scales 0.96-1.04 in every view; v5 centres them on a scale the robot
estimated from its own earlier rounds. Deployable inputs only: onboard depth, the localiser's
estimate and reported covariance, the facility map. No true pose, object or label is read.

- ``fit_view``: frozen v4's refinement of one calibration view -> fitted scale, trusted or not.
- ``estimate_scale``: median fitted scale over trusted fits ("med").
- ``pair_ratio``: two frames at one pose -> median per-pixel depth ratio - 1 (frame-to-frame
  scale change; independent of the pose, so free of the scale-translation coupling).
- ``estimate_jitter``: robust std of the pair ratios / sqrt(2).
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..v3.eval import estimated_pose, noisy_depth, reported_prior
from ..v4 import frozen_v4
from ..v4.geometry import refine_pose_v4

CAL_GEOMETRY = frozen_v4.GEOMETRY  # the per-view fits the calibration pools
MAD_TO_SIGMA = 1.4826


def fit_view(spec, frames, vp, depth_level: str, pose_level: str, prior_level: str) -> dict:
    from ..nav.localize import map_outlines

    depth = noisy_depth(spec, vp.id, frames.depth(vp.id), depth_level)
    est = estimated_pose(spec, vp, pose_level)
    ref = refine_pose_v4(
        depth, spec.camera, est, spec.zone, map_outlines(spec), CAL_GEOMETRY,
        prior=reported_prior(prior_level),
    )  # fmt: skip
    return {"vp": vp.id, "ok": bool(ref.ok), "conflict": bool(ref.conflict), "scale": ref.scale}


def pair_ratio(a: np.ndarray, b: np.ndarray, min_pixels: int = 1000) -> float | None:
    """Median of b / a over pixels valid in both frames, minus 1."""
    ok = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
    if ok.sum() < min_pixels:
        return None
    return float(np.median(b[ok].astype(float) / a[ok].astype(float)) - 1.0)


def _episode(args: tuple) -> dict:
    ns, eid, depth_level, pose_level, prior_level, pairs, *rest = args
    every_view = bool(rest and rest[0])
    from ..framestore import FrameStore

    spec = next(s for s in _specs(ns) if s.episode_id == eid)
    frames = FrameStore(f"renders/{ns}").episode(eid)
    views = [
        fit_view(spec, frames, vp, depth_level, pose_level, prior_level)
        for vp in (spec.initial_viewpoint, *spec.candidate_viewpoints)
    ]
    ratios = []
    stops = (
        (spec.initial_viewpoint, *spec.candidate_viewpoints)
        if every_view
        else (spec.initial_viewpoint,)
    )
    for vp in stops:  # stationary repeat at a stop: frames rep 2k and 2k + 1
        clean = frames.depth(vp.id)
        for k in range(pairs):
            a = noisy_depth(spec, vp.id, clean, depth_level, rep=2 * k)
            b = noisy_depth(spec, vp.id, clean, depth_level, rep=2 * k + 1)
            ratios.append(pair_ratio(a, b))
    return {"episode": eid, "views": views, "pair_ratios": ratios}


_SPEC_CACHE: dict[str, list] = {}


def _specs(ns: str) -> list:
    if ns not in _SPEC_CACHE:
        from ..serialize import load_episode_set

        _SPEC_CACHE[ns] = load_episode_set(f"data/episodes/gazebo-{ns}.json")[0]
    return _SPEC_CACHE[ns]


def estimate_scale(fits: list[dict]) -> dict:
    s = np.array([f["scale"] for f in fits if f["ok"]])
    if not len(s):
        return {"center": 1.0, "n_ok": 0}
    q = np.quantile(s, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {
        "center": float(np.median(s)),
        "n_ok": int(len(s)),
        "mad_sigma": float(MAD_TO_SIGMA * np.median(np.abs(s - np.median(s)))),
        "quantiles_05_25_50_75_95": [float(x) for x in q],
    }


def estimate_jitter(ratios: list[float | None]) -> dict:
    r = np.array([x for x in ratios if x is not None])
    if len(r) < 2:
        return {"sigma": math.nan, "n_pairs": int(len(r))}
    mad = MAD_TO_SIGMA * float(np.median(np.abs(r - np.median(r))))
    return {
        "sigma": mad / math.sqrt(2),
        "n_pairs": int(len(r)),
        "std_sigma": float(r.std() / 2**0.5),
    }


def calibrate(
    ns: str,
    depth_level: str,
    pose_level: str,
    prior_level: str | None = None,
    episodes: int | None = None,
    pairs: int = 1,
    workers: int = 6,
    cache: Path | None = None,
    pairs_every_view: bool = False,
) -> dict:
    """Self-calibration on the first ``episodes`` episodes of ``ns`` (all if None)."""
    prior_level = prior_level or pose_level
    name = f"{ns}-{depth_level}x{pose_level}-pr{prior_level}-n{episodes or 'all'}-p{pairs}"
    if pairs_every_view:  # one stationary pair set at every stop instead of the initial view
        name += "v"
    if cache is not None and (cache / f"{name}.json").exists():
        return json.loads((cache / f"{name}.json").read_text())
    from .maclock import require_free

    require_free()
    eids = [s.episode_id for s in _specs(ns)][:episodes]
    jobs = [(ns, e, depth_level, pose_level, prior_level, pairs, pairs_every_view) for e in eids]
    with ProcessPoolExecutor(min(workers, len(jobs))) as ex:
        per_ep = list(ex.map(_episode, jobs))
    fits = [v for e in per_ep for v in e["views"]]
    out = {
        "name": name,
        "source": {"ns": ns, "depth": depth_level, "pose": pose_level, "prior": prior_level},
        "episodes": len(eids),
        "views": len(fits),
        "scale": estimate_scale(fits),
        "jitter": estimate_jitter([r for e in per_ep for r in e["pair_ratios"]]),
        "per_episode": per_ep,
    }
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{name}.json").write_text(json.dumps(out) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    from ..v3.eval import DEV_NAMESPACES

    ap = argparse.ArgumentParser(prog="activeperception.v5.calib")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--conditions", default="D1xL1,D2xL2,D3xL1,D3xP0")
    ap.add_argument("--episodes", type=int, default=None)
    ap.add_argument("--pairs", type=int, default=1)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cache", default="runs/v5-dev/calib")
    ap.add_argument("--pairs-every-view", action="store_true")
    args = ap.parse_args(argv)
    if args.ns not in DEV_NAMESPACES:
        raise SystemExit(f"{args.ns}: not development data (allowed: {DEV_NAMESPACES})")
    for cond in args.conditions.split(","):
        prior = None
        if ":" in cond:
            cond, prior = cond.split(":")
        d, p = cond.split("x")
        c = calibrate(
            args.ns, d, p, prior, args.episodes, args.pairs, args.workers, Path(args.cache),
            args.pairs_every_view,
        )  # fmt: skip
        s, j = c["scale"], c["jitter"]
        print(
            f"{c['name']}: centre {s['center']:.4f} from {s['n_ok']} / {c['views']} fits "
            f"(q05-q95 {s['quantiles_05_25_50_75_95'][0]:.3f}-"
            f"{s['quantiles_05_25_50_75_95'][4]:.3f}); jitter {j['sigma']:.4f} "
            f"({j['n_pairs']} pairs)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
