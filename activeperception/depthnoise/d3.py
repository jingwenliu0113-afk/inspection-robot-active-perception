"""D3: the R0b D2 level plus what the real D435 / D455 planes showed the model misses
(decision 028 §5; numbers from results/depthnoise/comparison.json, 1-3 m, worst camera).

On top of D2 (random 2 % at 2 m growing with z^2, 3 % dropout, 3 px two-sided edge band):

- scale: -2.5 % (D435 under-estimates range by up to 2.48 %; the model only had +) and a per-view
  jitter of 1.0 % (exploratory: the whole region moves frame to frame by up to 1.04 %);
- correlation: 1/e lag 18 simulated pixels (kernel sigma 9 px; the model had 6);
- fixed pattern: a third of the random variance is a field fixed to the camera (the same in every
  view; D435 at 1 m: fixed / spatial sigma 0.57);
- stereo occlusion: left of every near edge, a band of width f * B * (1/z_near - 1/z_far) pixels
  is missing (Intel D400 datasheet geometry, B = 0.095 m, the wider D455 baseline). Not measured
  here (planes have no edges): an estimate from the stereo geometry.

Development only: a formal D3 test needs its own decision and new data (decision 028 §5).
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from ..r0b import DEPTH_LEVELS
from ..r0b_noise import apply_depth_noise, correlated_field

BIAS = -0.025
SCALE_JITTER = 0.010
CORR_PX = 9.0
FIXED_SHARE = 1 / 3
BASELINE_M = 0.095
EDGE_JUMP_M = 0.10
FIXED_SEED = 20261015


def _sigma(z: np.ndarray) -> np.ndarray:
    d2 = DEPTH_LEVELS["D2"]
    return d2.rel_at_2m * 2.0 * (z / 2.0) ** 2


_FIXED: dict[tuple[int, int], np.ndarray] = {}


def fixed_field(shape: tuple[int, int]) -> np.ndarray:
    if shape not in _FIXED:
        _FIXED[shape] = correlated_field(shape, CORR_PX, np.random.default_rng(FIXED_SEED))
    return _FIXED[shape]


def occlusion_band(depth: np.ndarray, focal_px: float) -> np.ndarray:
    """Pixels hidden from the second imager: left of each far -> near step along a row."""
    z = np.where(np.isfinite(depth), depth, np.inf)
    band = np.zeros(depth.shape, dtype=bool)
    rows, cols = np.nonzero(z[:, :-1] - z[:, 1:] > EDGE_JUMP_M)  # z[j] far, z[j+1] near
    for r, c in zip(rows, cols, strict=True):
        near, far = z[r, c + 1], z[r, c]
        w = focal_px * BASELINE_M * (1 / near - (0 if math.isinf(far) else 1 / far))
        band[r, max(0, c + 1 - int(round(w))) : c + 1] = True
    return band


def apply_d3(depth: np.ndarray, focal_px: float, rng: np.random.Generator) -> np.ndarray:
    clean = depth.astype(float)
    base = dataclasses.replace(DEPTH_LEVELS["D2"], name="D3", bias=0.0, corr_px=CORR_PX)
    # D2 machinery (independent part, edges, dropout, mm) with the longer correlation
    noisy = apply_depth_noise(clean, base, rng)
    valid = np.isfinite(noisy)
    # replace part of the independent variance by the camera-fixed field
    resid = noisy - clean
    fixed = fixed_field(clean.shape) * _sigma(np.where(np.isfinite(clean), clean, 0.0))
    mixed = math.sqrt(1 - FIXED_SHARE) * resid + math.sqrt(FIXED_SHARE) * fixed
    out = np.where(valid, clean + np.where(np.isfinite(mixed), mixed, resid), np.nan)
    out = out * (1 + BIAS + SCALE_JITTER * rng.standard_normal())
    out[occlusion_band(clean, focal_px)] = np.nan
    return out
