"""v5 development configurations (decision 033): frozen v4 with the depth-scale hypotheses
centred on a calibrated scale instead of 1.0."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from ..v4 import frozen_v4
from ..v4.geometry import GeometryConfigV4


@dataclass(frozen=True)
class GeometryConfigV5(GeometryConfigV4):
    """v4 + ``see_scale``: the see-through test reads measured depth / see_scale (1 = raw depth,
    as v4). Candidate (decision 033 development notes): the calibrated scale removes the
    camera's fixed bias; what is left is the frame-to-frame jitter, symmetric about 0."""

    see_scale: float = 1.0
    # see-v5 (appendix A): a location is seen through when no pose of the 27-pose set is blocked
    # and at least see_k poses see it; poses without enough valid depth do not veto. 0 = v3 rule.
    see_k: int = 0
    see_bracket: bool = True  # missing poses must lie between seen poses (False: ablation)


BASE = frozen_v4.GEOMETRY
N_HYP = 5
CAL_RESOLUTION = 0.005  # the calibration's grid (v4's fine scale step)


def band_for(rule: str, jitter_sigma: float) -> float:
    """Half-width of the hypothesis band.

    ``f0.02``: fixed 2 %. ``j2``: 2 x the measured frame-to-frame jitter + the calibration's
    resolution, at least ``CAL_RESOLUTION``."""
    if rule.startswith("f"):
        return float(rule[1:])
    if rule.startswith("j"):
        k = float(rule[1:])
        j = 0.0 if not np.isfinite(jitter_sigma) else jitter_sigma
        return max(CAL_RESOLUTION, k * j) + CAL_RESOLUTION
    raise ValueError(f"unknown band rule {rule}")


def calibrated(
    center: float,
    band: float,
    name: str,
    base: GeometryConfigV4 = BASE,
    n: int = N_HYP,
    see: bool = False,
    see_k: int = 0,
) -> GeometryConfigV5:
    scales = tuple(round(float(center + band * t), 4) for t in np.linspace(-1.0, 1.0, n))
    return with_see(base, see_k, name, hyp_scales=scales, see_scale=center if see else 1.0)


def with_see(base: GeometryConfigV4, see_k: int, name: str, **changes) -> GeometryConfigV5:
    """``base`` (e.g. frozen v4) as a v5 config with the see-v5 rule and other changes."""
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields |= {"name": name, "see_k": see_k, **changes}
    return GeometryConfigV5(**fields)
