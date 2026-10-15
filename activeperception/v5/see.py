"""see-v5 (decision 033 appendix A, development): robust see-through that does not let a pose
without enough valid depth veto a location.

v3 / v4 (``v3.geometry.robust_visibility_v3``) clear a location only if it is seen through from
every pose of the 27-pose uncertainty set; a pose whose 5 x 5 neighbourhood has too few valid
pixels counts as "not seen". Under D3 the one-sided stereo-occlusion band and dropout make that
happen for some pose of most locations: at the true pose with a 10 cm margin D3 cleared 18 % fewer
locations than noise-free depth (dev), while a depth-scale correction changed nothing.

Per axis point and pose the state is seen / blocked / missing / outside:
- blocked: some valid pixel of the neighbourhood is in front of the point (minus the tolerance);
- seen: no such pixel and enough valid pixels (v3's per-pose test);
- missing: too few valid pixels; outside: the point projects outside the image.

An axis point is seen through when no pose is blocked or outside, at least ``k`` poses are seen,
and (``bracket``) every missing pose projects strictly between seen poses in image column.
Why bracketing: the 27 poses stand for where the camera may really be; clearing a point from the
other poses' pixels is only an interpolation across the missing ones. Random dropout and the thin
edge bands are holes inside valid evidence (bracketed); the one-sided stereo-occlusion band lies
against a nearer surface, whose side is blocked or unreached, so it keeps v3's behaviour there.
Out-of-image poses always veto (dev: no cost). ``k`` >= the number of poses is exactly v3.
"""

from __future__ import annotations

import numpy as np

from ..geometry import project_points
from ..nav.localize import pose_set
from ..sensing import LOCATION_TOLERANCE_M, ZONE_LEVELS, location_axis_points, location_grid
from ..v3.geometry import SEE_HALF_PX, SEE_MIN_VALID, robust_visibility_v3

SEEN, BLOCKED, MISSING, OUTSIDE = 0, 1, 2, 3
UNKNOWN = MISSING  # backwards name


def point_states(
    depth: np.ndarray,
    camera,
    pose,
    zone,
    half: int = SEE_HALF_PX,
    min_valid: float = SEE_MIN_VALID,
    tolerance: float = LOCATION_TOLERANCE_M,
    with_u: bool = False,
):
    """State of every (location, level) axis point from one pose (and its image column)."""
    pts = location_axis_points(zone, location_grid(zone))
    uv, planar, in_fov = project_points(camera, pose, pts)
    st = np.full(len(pts), OUTSIDE, dtype=np.int8)
    idx = np.flatnonzero(in_fov)
    if len(idx):
        offs = np.arange(-half, half + 1)
        u0 = np.floor(uv[idx, 0]).astype(int)
        v0 = np.floor(uv[idx, 1]).astype(int)
        uu = np.clip(u0[:, None, None] + offs[None, None, :], 0, camera.width - 1)
        vv = np.clip(v0[:, None, None] + offs[None, :, None], 0, camera.height - 1)
        patch = depth[vv, uu].astype(float)
        valid = ~np.isnan(patch)  # +inf (no return within range) is a valid "far" reading
        front = (valid & (patch < planar[idx, None, None] - tolerance)).any(axis=(1, 2))
        enough = valid.sum(axis=(1, 2)) >= min_valid * patch[0].size
        st[idx] = np.where(front, BLOCKED, np.where(enough, SEEN, MISSING))
    return (st, uv[:, 0]) if with_u else st


def robust_visibility_v5(
    depth, camera, pose, zone, dxy, dyaw, k: int, bracket: bool = True
) -> tuple[float, ...]:
    poses = pose_set(pose, dxy, dyaw)
    if k >= len(poses):
        return robust_visibility_v3(depth, camera, pose, zone, dxy, dyaw, True)
    su = [point_states(depth, camera, p, zone, with_u=True) for p in poses]
    s = np.array([x[0] for x in su])
    ok = ~((s == BLOCKED) | (s == OUTSIDE)).any(axis=0) & ((s == SEEN).sum(axis=0) >= k)
    if bracket:
        u = np.array([x[1] for x in su])
        lo = np.where(s == SEEN, u, np.inf).min(axis=0)
        hi = np.where(s == SEEN, u, -np.inf).max(axis=0)
        ok &= np.where(s == MISSING, (u > lo) & (u < hi), True).all(axis=0)
    per_loc = ok.reshape(len(location_grid(zone)), len(ZONE_LEVELS)).mean(axis=1)
    return tuple(float(v) for v in per_loc)
