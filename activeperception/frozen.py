"""Frozen experiment configuration (decision 009).

Changing anything here means a new version, a new decision log and a new test round;
v1 results are kept. Defaults elsewhere in the package remain the v0 values.
"""

from __future__ import annotations

from .decision import DecisionRule, DecisionRuleParams
from .detector import DETECTOR_VERSION, FROZEN_DETECTOR
from .episodes import GENERATOR_VERSION
from .labeling import LABELING_VERSION
from .policies import RuleNBVParams, RuleNBVPolicy

DECISION_VERSION = "decision-v1"
RULE_NBV_VERSION = "rule-nbv-v1"

DECISION_V1 = DecisionRuleParams(
    tau_present=0.7,
    tau_absent=0.05,
    n_sectors=8,
    min_coverage=0.25,
    effective_zone_fraction=0.3,
)
RULE_NBV_V1 = RuleNBVParams(
    w_coverage=0.0,
    w_visibility=1.0,
    w_novelty=0.5,
    w_attraction=0.0,
    w_unobstructed=0.0,
)
FORMAL_BUDGETS = (1, 2, 3, 5)
CURVE_BUDGETS = tuple(range(1, 9))
RANDOM_SEEDS = (0, 1, 2, 3, 4)
N_BOOT = 1000
BOOT_SEED = 0

VERSIONS = {
    "generator": GENERATOR_VERSION,
    "labeling": LABELING_VERSION,
    "detector": f"{DETECTOR_VERSION}:{FROZEN_DETECTOR}",
    "decision_rule": DECISION_VERSION,
    "rule_nbv": RULE_NBV_VERSION,
}


def decision_rule() -> DecisionRule:
    return DecisionRule(DECISION_V1, version=DECISION_VERSION)


def rule_nbv(visibility_cache: dict | None = None) -> RuleNBVPolicy:
    return RuleNBVPolicy(RULE_NBV_V1, DECISION_V1, visibility_cache, version=RULE_NBV_VERSION)
