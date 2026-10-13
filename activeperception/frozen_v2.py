"""Frozen v2 configuration (decision 012). v1 lives unchanged in ``frozen.py``.

Changing anything here means a v3, a new decision log and new held-out data.
"""

from __future__ import annotations

from .decision import DecisionRuleV2, DecisionRuleV2Params
from .detector import DETECTOR_VERSION, FROZEN_DETECTOR
from .episodes import GENERATOR_VERSION
from .frozen import BOOT_SEED, CURVE_BUDGETS, FORMAL_BUDGETS, N_BOOT, RANDOM_SEEDS  # noqa: F401
from .labeling import LABELING_VERSION
from .policies import RuleNBVv2Params, RuleNBVv2Policy
from .sensing import LOCATION_SAMPLES, LOCATION_TOLERANCE_M, OBJECT_RADIUS_PRIOR_M

DECISION_VERSION = "decision-v2"
RULE_NBV_VERSION = "rule-nbv-v2"

DECISION_V2 = DecisionRuleV2Params(tau_present=0.7, tau_absent=0.02, tau_clear=1.0, col_min=1.0)
RULE_NBV_V2 = RuleNBVv2Params(
    w_gain=1.0, p_unknown=0.5, w_novelty=0.0, w_attraction=0.0, w_visibility=0.0
)

VERSIONS = {
    "generator": GENERATOR_VERSION,
    "labeling": LABELING_VERSION,
    "detector": f"{DETECTOR_VERSION}:{FROZEN_DETECTOR}",
    "decision_rule": DECISION_VERSION,
    "rule_nbv": RULE_NBV_VERSION,
    "locations": (
        f"{LOCATION_SAMPLES} pts, r_obj {OBJECT_RADIUS_PRIOR_M} m, tol {LOCATION_TOLERANCE_M} m"
    ),
}


def decision_rule() -> DecisionRuleV2:
    return DecisionRuleV2(DECISION_V2, version=DECISION_VERSION)


def rule_nbv(cache: dict | None = None) -> RuleNBVv2Policy:
    return RuleNBVv2Policy(RULE_NBV_V2, DECISION_V2, cache, version=RULE_NBV_VERSION)
