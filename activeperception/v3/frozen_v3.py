"""Frozen v3 (decision 025). v1 / v2 / decision 016 stay unchanged in their own modules.

Chosen on development data only (decision 024, docs/v3-development.md). Changing anything here
after the formal run means a v4, a new decision log and new data.
"""

from __future__ import annotations

from .. import frozen_v2
from ..detector import DETECTOR_VERSION, FROZEN_DETECTOR
from . import eval as v3e
from . import geometry as g

CONFIG_NAME = "v3"
# m6p on the development data: no occupied-location clearance in any of the five error
# conditions (m4p too); the larger margin keeps more slack for unseen data at equal cost in
# D1xL1. The localiser-prior gate (k = 3) removed the wrong convergences (max error 21 -> 12 cm).
MARGIN_OK = (0.06, 0.03)
PRIOR_K = 3.0
GEOMETRY = g.GeometryConfig(margin_ok=MARGIN_OK, prior_k=PRIOR_K, name=CONFIG_NAME)
# rule-nbv-v3 (novelty tie-break) dropped: no gain on the development data (Rule budget 2
# 0.983 -> 0.975, budget 3 1.000 both) -> the frozen rule-nbv-v2 stays.
TIE_BREAK = False


def describe() -> dict:
    return {
        "detector": f"{DETECTOR_VERSION}:{FROZEN_DETECTOR}",
        "decision_thresholds": "decision-v2 (unchanged)",
        "tau_present": frozen_v2.DECISION_V2.tau_present,
        "tau_absent": frozen_v2.DECISION_V2.tau_absent,
        "zone_gating": {"slack_m": v3e.ZONE_SLACK_M, "min_valid": v3e.GATE_MIN_VALID},
        "see_through_v3": {"half_px": g.SEE_HALF_PX, "min_valid": g.SEE_MIN_VALID},
        "nav_pose_v3": {
            "depth_prior_rel_at_2m": g.SPEC_REL_AT_2M,
            "sigma_fit_m": g.SIGMA_FIT_M,
            "max_range_m": GEOMETRY.max_range,
            "scales": [*g.SCALES_COARSE, f"fine +-{g.SCALE_FINE_STEP}"],
            "min_eigenvalue": GEOMETRY.min_eigenvalue,
            "prior_k": GEOMETRY.prior_k,
            "prior_floor": list(v3e.PRIOR_FLOOR),
        },
        "nav_margin_v3": {
            "ok": list(GEOMETRY.margin_ok),
            "fallback": f"max({list(GEOMETRY.margin_fallback)}, {GEOMETRY.prior_k} sigma)",
        },
        "rule_nbv_v3_tie_break": TIE_BREAK,
    }
