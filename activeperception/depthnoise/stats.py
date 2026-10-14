"""Depth error statistics from (measured, reference) pairs - the same numbers for a real sensor
against its reference depth and for the R0b model against clean Gazebo depth, so the two can be
compared parameter by parameter (decision 028).

Per frame pair (planar depth in metres, NaN / 0 = no measurement):

- ``bins``: per reference-range bin, RMS of the error after removing the global scale, the
  median relative error (scale bias: measured / reference - 1) and the invalid fraction;
- ``fit``: sigma(z) = a * z^p, least squares in log space over the bins (R0b assumes p = 2,
  a = rel_at_2m / 2 m);
- ``edges``: within ``edge_px`` of a reference discontinuity (> ``jump`` m), the share of pixels
  that are missing, "flying" (more than 3 sigma(z) from both sides) or on one side;
- ``corr_px``: correlation length of the residual (lag at which the autocorrelation drops to
  1 / e), on smooth regions only.

    uv run python -m activeperception.depthnoise.stats model --renders renders/v3-dev \\
        --level D1 --out runs/depthnoise/model-D1.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BINS_M = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)
JUMP_M = 0.10


@dataclass
class Accumulator:
    """Sums over many frames (frames differ in size and content)."""

    edge_px: int = 3
    jump: float = JUMP_M

    def __post_init__(self):
        n = len(BINS_M) - 1
        self.n = np.zeros(n)
        self.n_valid = np.zeros(n)
        self.rel = [[] for _ in range(n)]  # subsampled relative errors per bin
        self.edge = {"n": 0, "missing": 0, "flying": 0, "near_side": 0, "far_side": 0}
        self.acf: list[np.ndarray] = []

    def add(self, meas: np.ndarray, ref: np.ndarray, rng: np.random.Generator) -> None:
        meas = np.where(np.isfinite(meas) & (meas > 0), meas, np.nan).astype(float)
        ok_ref = np.isfinite(ref) & (ref > 0)
        idx = np.digitize(ref, BINS_M) - 1
        disc = discontinuity(ref, self.jump, self.edge_px)
        smooth = ok_ref & ~disc
        for b in range(len(BINS_M) - 1):
            m = smooth & (idx == b)
            self.n[b] += m.sum()
            v = m & np.isfinite(meas)
            self.n_valid[b] += v.sum()
            r = (meas[v] / ref[v]) - 1.0
            if len(r) > 2000:
                r = rng.choice(r, 2000, replace=False)
            self.rel[b].extend(r.tolist())
        self._edges(meas, ref, disc & ok_ref)
        self._acf(meas, ref, smooth)

    def _edges(self, meas, ref, disc) -> None:
        near, far = local_extremes(ref, self.edge_px)
        e = self.edge
        e["n"] += int(disc.sum())
        miss = disc & ~np.isfinite(meas)
        e["missing"] += int(miss.sum())
        v = disc & np.isfinite(meas)
        tol = np.maximum(0.03, 0.02 * ref)
        on_near = v & (np.abs(meas - near) <= tol)
        on_far = v & (np.abs(meas - far) <= tol)
        e["near_side"] += int((on_near & ~on_far).sum())
        e["far_side"] += int((on_far & ~on_near).sum())
        e["flying"] += int((v & ~on_near & ~on_far & (meas > near) & (meas < far)).sum())

    def _acf(self, meas, ref, smooth, max_lag: int = 12) -> None:
        res = np.where(smooth & np.isfinite(meas), meas - ref, np.nan)
        res = res - np.nanmedian(res) if np.isfinite(res).any() else res
        out = []
        for lag in range(max_lag + 1):
            a, b = res[:, : res.shape[1] - lag], res[:, lag:]
            m = np.isfinite(a) & np.isfinite(b)
            out.append(np.mean(a[m] * b[m]) if m.sum() > 100 else np.nan)
        out = np.array(out)
        if np.isfinite(out[0]) and out[0] > 0:
            self.acf.append(out / out[0])

    def result(self) -> dict:
        bins = []
        for b in range(len(BINS_M) - 1):
            r = np.array(self.rel[b])
            if len(r) < 50:
                continue
            z = (BINS_M[b] + BINS_M[b + 1]) / 2
            med = float(np.median(r))
            rms = float(np.sqrt(np.mean((r - med) ** 2)))
            mad = float(1.4826 * np.median(np.abs(r - med)))
            bins.append(
                {
                    "z_m": z,
                    "n": int(self.n[b]),
                    "invalid": float(1 - self.n_valid[b] / max(1, self.n[b])),
                    "scale_bias": med,
                    "rel_rms": rms,
                    "rel_robust_sigma": mad,
                    "abs_robust_sigma_m": mad * z,
                }
            )
        e = self.edge
        acf = np.nanmean(np.array(self.acf), axis=0) if self.acf else None
        return {
            "bins": bins,
            "fit": fit_power(bins),
            "edges": {k: (v / e["n"] if k != "n" and e["n"] else v) for k, v in e.items()},
            "corr_px": corr_length(acf),
            "acf": None if acf is None else [float(x) for x in acf],
        }


def discontinuity(ref: np.ndarray, jump: float, px: int) -> np.ndarray:
    """Pixels within ``px`` of a jump > ``jump`` between 4-neighbours of the reference."""
    r = np.where(np.isfinite(ref), ref, np.inf)
    j = np.zeros(ref.shape, dtype=bool)
    dx = np.abs(np.diff(r, axis=1)) > jump
    dy = np.abs(np.diff(r, axis=0)) > jump
    j[:, :-1] |= dx
    j[:, 1:] |= dx
    j[:-1, :] |= dy
    j[1:, :] |= dy
    return dilate(j, px)


def dilate(mask: np.ndarray, px: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(px):
        m = out.copy()
        m[1:, :] |= out[:-1, :]
        m[:-1, :] |= out[1:, :]
        m[:, 1:] |= out[:, :-1]
        m[:, :-1] |= out[:, 1:]
        out = m
    return out


def local_extremes(ref: np.ndarray, px: int) -> tuple[np.ndarray, np.ndarray]:
    """Nearest (min) and farthest (max) reference depth in a (2px+1)^2 window."""
    r = np.where(np.isfinite(ref), ref, np.nan)
    pad = np.pad(r, px, mode="edge")
    h, w = r.shape
    stack = np.stack(
        [pad[i : i + h, j : j + w] for i in range(2 * px + 1) for j in range(2 * px + 1)]
    )
    return np.nanmin(stack, axis=0), np.nanmax(stack, axis=0)


def fit_power(bins: list[dict]) -> dict | None:
    """abs sigma(z) = a z^p (robust sigma), log-space least squares."""
    pts = [(b["z_m"], b["abs_robust_sigma_m"]) for b in bins if b["abs_robust_sigma_m"] > 0]
    if len(pts) < 3:
        return None
    z, s = np.log([p[0] for p in pts]), np.log([p[1] for p in pts])
    p, loga = np.polyfit(z, s, 1)
    a = float(np.exp(loga))
    return {"a": a, "p": float(p), "sigma_at_2m_m": a * 2**p, "rel_at_2m": a * 2**p / 2}


def corr_length(acf) -> float | None:
    if acf is None or not np.isfinite(acf).all():
        return None
    below = np.flatnonzero(acf < np.exp(-1))
    if not len(below):
        return None
    k = int(below[0])
    a0, a1 = acf[k - 1], acf[k]  # linear interpolation of the 1/e crossing
    return float(k - 1 + (a0 - np.exp(-1)) / (a0 - a1))


def model_stats(renders: Path, level: str, max_frames: int, seed: int = 0) -> dict:
    """The R0b model on clean Gazebo depth (reference = the clean depth)."""
    from ..framestore import FrameStore
    from ..r0b import DEPTH_LEVELS
    from ..r0b_noise import apply_depth_noise, rng_for

    store = FrameStore(str(renders))
    dn = DEPTH_LEVELS[level]
    acc = Accumulator(edge_px=dn.edge_px)
    rng = np.random.default_rng(seed)
    frames = 0
    for e in store.episode_ids():
        ep = store.episode(e)
        for vp in ep.viewpoint_ids:
            if frames >= max_frames:
                break
            ref = ep.depth(vp).astype(float)
            meas = apply_depth_noise(ref, dn, rng_for(e, f"v{vp}", "depth", dn.name))
            acc.add(meas, ref, rng)
            frames += 1
    return {"source": f"R0b model {level} on {renders}", "frames": frames, **acc.result()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.depthnoise.stats")
    ap.add_argument("action", choices=["model"])
    ap.add_argument("--renders", default="renders/v3-dev")
    ap.add_argument("--level", default="D1")
    ap.add_argument("--max-frames", type=int, default=200)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    res = model_stats(Path(args.renders), args.level, args.max_frames)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: res[k] for k in ("frames", "fit", "edges", "corr_px")}, indent=1))
    for b in res["bins"]:
        print(b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
