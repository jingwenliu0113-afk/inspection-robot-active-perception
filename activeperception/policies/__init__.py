from .base import Policy, unvisited_candidates
from .oracle_nbv import OracleNBVPolicy, OracleNBVv2Policy
from .random_nbv import RandomNBVPolicy
from .rule_nbv import RuleNBVParams, RuleNBVPolicy
from .rule_nbv_v2 import RuleNBVv2Params, RuleNBVv2Policy
from .single_view import SingleViewPolicy

DEPLOYABLE_POLICIES = ("single", "random", "rule")
ALL_POLICIES = DEPLOYABLE_POLICIES + ("oracle",)

__all__ = [
    "ALL_POLICIES",
    "DEPLOYABLE_POLICIES",
    "OracleNBVPolicy",
    "OracleNBVv2Policy",
    "Policy",
    "RandomNBVPolicy",
    "RuleNBVParams",
    "RuleNBVPolicy",
    "RuleNBVv2Params",
    "RuleNBVv2Policy",
    "SingleViewPolicy",
    "unvisited_candidates",
]
