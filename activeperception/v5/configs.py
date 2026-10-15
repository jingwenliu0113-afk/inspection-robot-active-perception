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
) -> GeometryConfigV5:
    scales = tuple(round(float(center + band * t), 4) for t in np.linspace(-1.0, 1.0, n))
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields |= {"hyp_scales": scales, "name": name, "see_scale": center if see else 1.0}
    return GeometryConfigV5(**fields)
