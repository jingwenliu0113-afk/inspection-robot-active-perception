"""R0b noise models: a stereo RGB-D depth error model and a localisation / calibration error
model, applied to Gazebo observations (decision 022). Simulation only - not a real sensor.

Depth (``DepthNoise``), on planar depth in metres (NaN = no measurement):

- systematic scale error ``bias`` (+ = distances over-estimated, the direction in which a
  blocked line of sight can look "seen through");
- random error with standard deviation growing with the square of the distance, as for
  stereo matching, ``sigma(z) = rel_at_2m * 2 m * (z / 2 m)^2``, spatially correlated over
  ``corr_px`` pixels (block matching);
- depth discontinuities: within ``edge_px`` of a jump > ``edge_jump_m`` a pixel is either
  missing or a "flying pixel" (a value between the near and the far side);
- random missing pixels (``dropout``); millimetre quantisation.

Pose (``PoseNoise``): the estimate the robot believes in = true camera pose + independent
Gaussian errors in x, y, yaw (localisation) and in z, pitch (mast calibration, which the 2D
map refinement cannot correct).
"""

from __future__ import annotations

import dataclasses
import zlib
from dataclasses import dataclass

import numpy as np

from .types import Pose

SEED = 20261014


@dataclass(frozen=True)
class DepthNoise:
    name: str
    rel_at_2m: float
    bias: float
    corr_px: float
    edge_px: int
    edge_jump_m: float
    dropout: float


@dataclass(frozen=True)
class PoseNoise:
    name: str
    sigma_xy: float
    sigma_yaw: float
    sigma_z: float
    sigma_pitch: float


def rng_for(*keys: str | int) -> np.random.Generator:
    """Independent, reproducible stream per (episode, view, level, ...)."""
    words = [SEED] + [k if isinstance(k, int) else zlib.crc32(k.encode()) for k in keys]
    return np.random.default_rng(words)


def _gauss_kernel(sigma: float) -> np.ndarray:
    r = max(1, int(round(3 * sigma)))
    x = np.arange(-r, r + 1, dtype=float)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def correlated_field(
    shape: tuple[int, int], corr_px: float, rng: np.random.Generator
) -> np.ndarray:
    """Zero-mean, unit-variance Gaussian field smoothed over ``corr_px`` pixels."""
    f = rng.standard_normal(shape)
    if corr_px > 0:
        k = _gauss_kernel(corr_px)
        pad = len(k) // 2
        f = np.pad(f, pad, mode="reflect")
        f = np.apply_along_axis(lambda r: np.convolve(r, k, mode="valid"), 1, f)
        f = np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, f)
        f /= np.sqrt((np.outer(k, k) ** 2).sum())  # exact variance of the smoothed white noise
    return f


def _window(a: np.ndarray, r: int, fn) -> np.ndarray:
    p = np.pad(a, r, mode="edge")
    w = np.lib.stride_tricks.sliding_window_view(p, (2 * r + 1, 2 * r + 1))
    return fn(w, axis=(-2, -1))


def edge_band(depth: np.ndarray, jump_m: float, px: int) -> np.ndarray:
    """Pixels within ``px`` of a depth discontinuity (a jump > ``jump_m`` to a 4-neighbour, or
    a border with missing depth)."""
    d = np.where(np.isfinite(depth), depth, np.nan)
    e = np.zeros(depth.shape, dtype=bool)
    for axis in (0, 1):
        diff = np.abs(np.diff(d, axis=axis))
        jump = ~(diff <= jump_m)  # NaN on either side counts as a jump
        lo = [slice(None)] * 2
        hi = [slice(None)] * 2
        lo[axis], hi[axis] = slice(0, -1), slice(1, None)
        e[tuple(lo)] |= jump
        e[tuple(hi)] |= jump
    return _window(e, px, np.max) if px > 0 else e


def apply_depth_noise(depth: np.ndarray, n: DepthNoise, rng: np.random.Generator) -> np.ndarray:
    z = depth.astype(np.float64)
    valid = np.isfinite(z) & (z > 0)
    zz = np.where(valid, z, 0.0)
    sigma = n.rel_at_2m * 2.0 * (zz / 2.0) ** 2
    out = zz * (1.0 + n.bias) + sigma * correlated_field(z.shape, n.corr_px, rng)
    band = edge_band(z, n.edge_jump_m, n.edge_px) & valid
    if n.edge_px > 0:
        near = _window(np.where(valid, zz, np.inf), n.edge_px, np.min)
        far = _window(np.where(valid, zz, -np.inf), n.edge_px, np.max)
        flying = band & (rng.random(z.shape) < 0.5)
        u = rng.random(z.shape)
        out = np.where(flying, near + u * (far - near), out)
        out[band & ~flying] = np.nan
    out[rng.random(z.shape) < n.dropout] = np.nan
    out = np.round(out * 1000.0) / 1000.0
    out[~valid] = depth[~valid]  # no return stays no return
    out[out <= 0] = np.nan
    return out.astype(np.float32)


def perturb_pose(pose: Pose, n: PoseNoise, rng: np.random.Generator) -> Pose:
    e = rng.standard_normal(5)
    return dataclasses.replace(
        pose,
        x=pose.x + n.sigma_xy * e[0],
        y=pose.y + n.sigma_xy * e[1],
        yaw=pose.yaw + n.sigma_yaw * e[2],
        z=pose.z + n.sigma_z * e[3],
        pitch=pose.pitch + n.sigma_pitch * e[4],
    )
