"""v6 development configurations (decision 037 appendix A). Frozen v5 plus one change each."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ..v5 import frozen_v5
from ..v5.configs import GeometryConfigV5


@dataclass(frozen=True)
class GeometryConfigV6(GeometryConfigV5):
    # H-P: a conflict (the view would be blind) whose fit-cost ratio is <= hp_c keeps the
    # localiser's pose with the failed-fit margin. 0 = off (v5).
    hp_c: float = 0.0
    # B-floor: the covariance floor the localiser reports (None = v3.eval.PRIOR_FLOOR).
    prior_floor: tuple[float, float] | None = None
    # development ceiling only - the true pose for every view, never blind. Not deployable.
    oracle_pose: bool = False


def from_v5(name: str, **changes) -> GeometryConfigV6:
    base = frozen_v5.GEOMETRY
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    return GeometryConfigV6(**(fields | {"name": name, **changes}))


C_MAIN = 1.2  # the user's choice (2026-10-16); 1.3 is the sensitivity check, 1.5 not used
C_SENSITIVITY = 1.3
FLOOR = (0.03, 0.015)  # B-floor: 3 x v3.eval.PRIOR_FLOOR

ARMS = {  # appendix A.1
    "B0": frozen_v5.GEOMETRY,
    "HP12": from_v5("v6-hp1.2", hp_c=C_MAIN),
    "HP13": from_v5("v6-hp1.3", hp_c=C_SENSITIVITY),
    "Bfloor": from_v5("v5-floor3", prior_floor=FLOOR),
    "Oracle": from_v5("v5-oracle-pose", oracle_pose=True),
}
DEPLOYABLE = ("B0", "HP12", "HP13", "Bfloor")
