from .base import Policy, unvisited_candidates
from .oracle_nbv import OracleNBVPolicy
from .random_nbv import RandomNBVPolicy
from .rule_nbv import RuleNBVParams, RuleNBVPolicy
from .single_view import SingleViewPolicy

DEPLOYABLE_POLICIES = ("single", "random", "rule")
ALL_POLICIES = DEPLOYABLE_POLICIES + ("oracle",)

__all__ = [
    "ALL_POLICIES",
    "DEPLOYABLE_POLICIES",
    "OracleNBVPolicy",
    "Policy",
    "RandomNBVPolicy",
    "RuleNBVParams",
    "RuleNBVPolicy",
    "SingleViewPolicy",
    "unvisited_candidates",
]
