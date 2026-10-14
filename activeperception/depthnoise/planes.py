"""Real stereo depth on a plane at laser-measured distances (Rustler et al. 2025, OSF f2seb,
CC BY 4.0) -> the numbers the R0b model assumes (decision 028).

    uv run python -m activeperception.depthnoise.planes --root data/raw/depthnoise \\
        --out results/depthnoise/planes.json

Per camera and distance, on a central region 0.30 m x 0.30 m on the plane (all frames):

- ``bias``: median depth / laser distance - 1 (the scale error R0b models as +1 / +2 %);
- ``spatial_sigma``: robust sigma of the residual after a plane fit, per frame (what one view
  sees: random + fixed-pattern error); ``temporal_sigma``: per-pixel sigma across frames;
  ``fixed_sigma``: the plane-fit residual of the per-pixel mean (pattern that repeats);
- ``invalid_roi`` / ``invalid_frame``: missing pixels on the plane / in the whole frame;
- ``quant_step_m``: the smallest depth step present (disparity quantisation);
- ``corr``: 1/e lag of the per-frame residual autocorrelation (x and y), converted from the
  stored pixels to radians and then to pixels of the simulated camera (640 px, 60 deg).

The depth PNGs are aligned to the colour stream (D435 640x480, D455 1280x720), so pixel
quantities are measured in colour pixels and converted with the colour focal length.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

ROI_HALF_M = 0.15
SIM_FX = 320 / math.tan(math.radians(30))  # Core / B camera: 640 px, 60 deg horizontal
CAMERAS = {"D435": 0.050, "D455": 0.095}  # stereo baseline (m), Intel datasheet
NAME = re.compile(r"^planes/(?P<dist>\d+)/rgbd/(?P<cam>[^/]+)/[^/]*_depth_(?P<i>\d+)\.png$")


def frames(root: Path, cam: str) -> dict[int, list[Path]]:
    """planes/<distance cm>/rgbd/<camera>/<date>_<time>_depth_<i>.png"""
    out = defaultdict(list)
    for p in sorted(root.rglob("*.png")):
        m = NAME.match(p.relative_to(root).as_posix())
        if m and m["cam"] == cam:
            out[int(m["dist"])].append(p)
    return dict(out)


def load(paths: list[Path]) -> np.ndarray:
    """Unique frames, metres, NaN = missing (the recordings contain exact duplicates)."""
    from PIL import Image

    seen, out = set(), []
    for p in paths:
        a = np.array(Image.open(p))
        h = hashlib.md5(a.tobytes()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(np.where(a > 0, a.astype(float) / 1000.0, np.nan))
    return np.stack(out)


def plane_residual(z: np.ndarray) -> np.ndarray:
    yy, xx = np.indices(z.shape)
    m = np.isfinite(z)
    if m.sum() < 50:
        return np.full(z.shape, np.nan)
    a = np.c_[xx[m], yy[m], np.ones(m.sum())]
    coef, *_ = np.linalg.lstsq(a, z[m], rcond=None)
    out = np.full(z.shape, np.nan)
    out[m] = z[m] - a @ coef
    return out


def robust_sigma(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else math.nan


def acf_1e(r: np.ndarray, axis: int, max_lag: int = 40) -> float | None:
    """1/e lag (pixels) of the autocorrelation of ``r`` along ``axis``."""
    r = r - np.nanmean(r)
    vals = []
    for lag in range(max_lag + 1):
        if axis == 1:
            a, b = r[:, : r.shape[1] - lag], r[:, lag:]
        else:
            a, b = r[: r.shape[0] - lag, :], r[lag:, :]
        m = np.isfinite(a) & np.isfinite(b)
        vals.append(np.mean(a[m] * b[m]) if m.sum() > 100 else np.nan)
    acf = np.array(vals) / vals[0]
    below = np.flatnonzero(acf < math.exp(-1))
    if not len(below) or not np.isfinite(acf[: below[0] + 1]).all():
        return None
    k = int(below[0])
    return float(k - 1 + (acf[k - 1] - math.exp(-1)) / (acf[k - 1] - acf[k]))


def quant_step(z: np.ndarray) -> float:
    u = np.unique(np.round(z[np.isfinite(z)], 4))
    d = np.diff(u)
    d = d[d > 0]
    return float(np.median(d)) if len(d) else math.nan


def analyse(stack: np.ndarray, z_nom: float, fx: float, cx: float, cy: float) -> dict:
    h = int(round(ROI_HALF_M * fx / z_nom))
    y0, x0 = int(round(cy)), int(round(cx))
    roi = stack[:, max(0, y0 - h) : y0 + h, max(0, x0 - h) : x0 + h]
    res = np.stack([plane_residual(f) for f in roi])
    mean = np.nanmean(np.where(np.isfinite(roi).all(axis=0), roi, np.nan), axis=0)
    my, mx = roi.shape[1] // 2, roi.shape[2] // 2
    centre = roi[:, my - 5 : my + 5, mx - 5 : mx + 5]
    cx_lags = [acf_1e(r, 1) for r in res]
    cy_lags = [acf_1e(r, 0) for r in res]
    to_sim = SIM_FX / fx
    lag_x = np.median([v for v in cx_lags if v is not None]) if any(cx_lags) else math.nan
    lag_y = np.median([v for v in cy_lags if v is not None]) if any(cy_lags) else math.nan
    return {
        "z_nominal_m": z_nom,
        "frames": int(len(stack)),
        "roi_px": list(roi.shape[1:]),
        "bias": float(np.nanmedian(centre) / z_nom - 1),
        "spatial_sigma_m": float(np.nanmedian([robust_sigma(r) for r in res])),
        "temporal_sigma_m": float(np.nanmedian(np.nanstd(roi, axis=0))),
        "fixed_sigma_m": robust_sigma(plane_residual(mean)),
        "invalid_roi": float(np.mean(~np.isfinite(roi))),
        "invalid_frame": float(np.mean(~np.isfinite(stack))),
        "quant_step_m": quant_step(roi[0]),
        "corr_1e_px": {"x": float(lag_x), "y": float(lag_y)},
        "corr_1e_sim_px": {"x": float(lag_x * to_sim), "y": float(lag_y * to_sim)},
    }


def fit(rows: list[dict], key: str) -> dict:
    """sigma(z) = a z^p over distances (log-space least squares)."""
    pts = [(r["z_nominal_m"], r[key]) for r in rows if r[key] > 0]
    z, s = np.log([p[0] for p in pts]), np.log([p[1] for p in pts])
    p, loga = np.polyfit(z, s, 1)
    a = float(np.exp(loga))
    return {"a": a, "p": float(p), "rel_at_2m": a * 2**p / 2}


def run(root: Path) -> dict:
    meta = {c: json.loads((root / "intrinsics" / f"{c}.json").read_text()) for c in CAMERAS}
    out = {}
    for cam in CAMERAS:
        col = meta[cam]["Color"]
        fx, (cx, cy) = col["focal_length"]["fx"], col["principal_point"].values()
        rows = [
            analyse(load(paths), d / 100.0, fx, cx, cy)
            for d, paths in sorted(frames(root, cam).items())
        ]
        out[cam] = {
            "distances": rows,
            "fit_spatial": fit(rows, "spatial_sigma_m"),
            "fit_temporal": fit(rows, "temporal_sigma_m"),
            "baseline_m": CAMERAS[cam],
            "colour_fx": fx,
        }
    return {
        "source": "Rustler et al. 2025, https://osf.io/f2seb/ (CC BY 4.0), planes, defaults",
        "roi_m": 2 * ROI_HALF_M,
        "cameras": out,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.depthnoise.planes")
    ap.add_argument("--root", default="data/raw/depthnoise")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    res = run(Path(args.root))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=1) + "\n")
    for cam, r in res["cameras"].items():
        print(cam, "spatial fit", r["fit_spatial"], "temporal fit", r["fit_temporal"])
        for d in r["distances"]:
            print(
                f"  {d['z_nominal_m']:.2f} m  bias {d['bias']:+.4f}  spatial "
                f"{d['spatial_sigma_m'] * 1000:.1f} mm  temporal {d['temporal_sigma_m'] * 1000:.1f}"
                f"  fixed {d['fixed_sigma_m'] * 1000:.1f}  invalid {d['invalid_roi']:.3f} / "
                f"{d['invalid_frame']:.3f}  step {d['quant_step_m'] * 1000:.1f} mm  corr(sim px) "
                f"{d['corr_1e_sim_px']['x']:.1f} / {d['corr_1e_sim_px']['y']:.1f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
