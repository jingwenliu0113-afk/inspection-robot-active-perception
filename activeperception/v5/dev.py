"""v5 development runner (decision 033): calibrate on one namespace, evaluate on another.

    uv run python -m activeperception.v5.dev --ns v3-dev --cal-ns v3-dev-dx \\
        --conditions D3xL1,D3xP0 --bands v4,f0.02,j2 --out runs/v5-dev/band

A condition is ``<depth>x<pose>`` with optional ``:<reported prior>`` and ``@<calibration depth
level>`` (drift stress: e.g. ``D3upxL1@D3`` evaluates a camera that drifted after a D3
calibration). Band ``v4`` = frozen v4 itself; ``truth:<rule>`` centres on the level's true mean
scale (a development ceiling, never a candidate). Development namespaces only.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..v3.eval import DEV_NAMESPACES, DRIFT_LEVELS, run
from ..v4 import frozen_v4
from ..v4.devreport import HEADER, row, summarize
from . import calib, configs, maclock

TRUE_SCALE = {"D0": 1.0, "D1": 1.01, "D2": 1.02, "D3": 0.975}  # development ceiling only


def parse(cond: str) -> dict:
    cal_depth = None
    if "@" in cond:
        cond, cal_depth = cond.split("@")
    prior = None
    if ":" in cond:
        cond, prior = cond.split(":")
    depth, pose = cond.split("x")
    return {"depth": depth, "pose": pose, "prior": prior, "cal_depth": cal_depth or depth}


def true_scale(depth: str) -> float:
    if depth in DRIFT_LEVELS:
        base, drift = DRIFT_LEVELS[depth]
        return TRUE_SCALE[base] * (1 + drift)
    return TRUE_SCALE[depth]


def guarded_run(job: tuple) -> dict | None:
    """``run`` unless another project holds the Mac heavy lock when the job starts."""
    if maclock.holder() is not None:
        return None
    return run(job)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v5.dev")
    ap.add_argument("--ns", default="v3-dev")
    ap.add_argument("--cal-ns", default="v3-dev-dx")
    ap.add_argument("--cal-episodes", type=int, default=None)
    ap.add_argument("--pairs", type=int, default=1)
    ap.add_argument("--conditions", default="D1xL1,D2xL2,D3xL1,D3xP0")
    ap.add_argument("--bands", default="v4,f0.02,j2")
    ap.add_argument("--gated", default="1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    maclock.require_free()
    for ns in (args.ns, args.cal_ns):
        if ns not in DEV_NAMESPACES:
            raise SystemExit(f"{ns}: not development data (allowed: {DEV_NAMESPACES})")
    if args.ns == args.cal_ns:
        raise SystemExit("calibrate on another namespace than the one evaluated")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path("runs/v5-dev/calib")
    jobs, names = [], []
    for cond in args.conditions.split(","):
        c = parse(cond)
        cal = None
        for band in args.bands.split(","):
            parts = band.split("+")  # e.g. "v4+k14", "f0.02+k14", "s:f0.02"
            see_k = next((int(x[1:]) for x in parts[1:] if x.startswith("k")), 0)
            free = "free" in parts[1:]  # see-v5 without bracketing (ablation)
            if parts[0] == "v4" and see_k == 0:
                cfg = frozen_v4.CONFIG_NAME
                name = f"{cond}-v4"
            elif parts[0] == "v4":
                cfg = configs.with_see(
                    frozen_v4.GEOMETRY, see_k, name=f"v5-{band}", see_bracket=not free
                )
                name = f"{cond}-{band}"
            else:
                if cal is None:
                    cal = calib.calibrate(
                        args.cal_ns, c["cal_depth"], c["pose"], c["prior"], args.cal_episodes,
                        args.pairs, args.workers, cache,
                    )  # fmt: skip
                    print(
                        f"calibration {cal['name']}: centre {cal['scale']['center']:.4f} "
                        f"(true {true_scale(c['cal_depth']):.4f}) from {cal['scale']['n_ok']} "
                        f"fits; jitter {cal['jitter']['sigma']:.4f} ({cal['jitter']['n_pairs']})",
                        flush=True,
                    )
                rule, centre, see = parts[0], cal["scale"]["center"], False
                if rule.startswith("s:"):  # + see-through on calibrated depth
                    rule, see = rule[2:], True
                if rule.startswith("truth:"):
                    rule, centre = rule.split(":")[1], true_scale(c["depth"])
                b = configs.band_for(rule, cal["jitter"]["sigma"])
                name = f"{cond}-{band}"
                cfg = configs.calibrated(centre, b, name=f"v5-{band}", see=see, see_k=see_k)
            prior = c["prior"]
            jobs.append(
                (args.ns, c["depth"], c["pose"], cfg, args.gated == "1", frozen_v4.TIE_BREAK, prior)
            )
            names.append(name.replace(":", "_").replace("@", "_cal"))
    print(HEADER, flush=True)
    with ProcessPoolExecutor(min(args.workers, len(jobs))) as ex:
        for name, job, r in zip(names, jobs, ex.map(guarded_run, jobs), strict=True):
            if r is None:
                print(f"{name}: SKIPPED (Mac heavy lock held by another project)", flush=True)
                continue
            cfg = job[3]
            r["v5"] = {"hyp_scales": list(getattr(cfg, "hyp_scales", ()) or ())}
            (out / f"{name}.json").write_text(json.dumps(r) + "\n")
            print(row(name, summarize(r)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
