"""Shared decision rule: observation history -> present / absent / inconclusive.

The same rule is used by every method so that the only difference between
Single View, Random NBV, Rule-based NBV and Oracle NBV is *which viewpoints were
visited*. The rule only reads deployable information (detections, sensor-derived
zone obstruction, viewpoint geometry).

``absent`` is never declared from "no detection" alone: it additionally requires
that enough distinct azimuth sectors around the zone were observed with an
unobstructed view of the zone (coverage proxy).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .types import Decision, DecisionOutput, DeployableEpisode, Observation

DECISION_RULE_VERSION = "decision-v0"


@dataclass(frozen=True)
class DecisionRuleParams:
    tau_present: float = 0.6  # max confidence needed to declare present
    tau_absent: float = 0.3  # max confidence must stay below this to declare absent
    n_sectors: int = 6  # azimuth sectors around the zone centre for coverage
    min_coverage: float = 0.5  # fraction of sectors with an effective view
    effective_zone_fraction: float = 0.5  # a view counts if the zone is this unobstructed


def sector_of(azimuth: float, n_sectors: int) -> int:
    return int((azimuth % (2 * math.pi)) / (2 * math.pi / n_sectors)) % n_sectors


class DecisionRule:
    def __init__(self, params: DecisionRuleParams | None = None, version: str | None = None):
        self.params = params or DecisionRuleParams()
        self.version = version or DECISION_RULE_VERSION

    def effective_sectors(self, history: Sequence[Observation]) -> set[int]:
        p = self.params
        return {
            sector_of(o.viewpoint.azimuth, p.n_sectors)
            for o in history
            if o.zone_visible_fraction >= p.effective_zone_fraction
        }

    def coverage(self, history: Sequence[Observation]) -> float:
        return len(self.effective_sectors(history)) / self.params.n_sectors

    def absent_geometry(self, history: Sequence[Observation]) -> bool:
        """The coverage part of the absent condition (reporting only; decide() unchanged)."""
        return self.coverage(history) >= self.params.min_coverage

    def decide(self, episode: DeployableEpisode, history: Sequence[Observation]) -> DecisionOutput:
        if not history:
            raise ValueError("decision requires at least one observation")
        p = self.params
        c_max = max(o.max_confidence for o in history)
        cov = self.coverage(history)
        features = {
            "max_confidence": c_max,
            "coverage": cov,
            "n_views": float(len(history)),
            "n_effective_views": float(
                sum(1 for o in history if o.zone_visible_fraction >= p.effective_zone_fraction)
            ),
        }
        if c_max >= p.tau_present:
            return DecisionOutput(Decision.PRESENT, confidence=c_max, features=features)
        if cov >= p.min_coverage and c_max < p.tau_absent:
            conf = cov * (1.0 - c_max)
            return DecisionOutput(Decision.ABSENT, confidence=conf, features=features)
        return DecisionOutput(Decision.INCONCLUSIVE, confidence=0.0, features=features)


# ---- decision-v2 (decision 011): absent needs free-space evidence for every location ---
DECISION_RULE_V2_VERSION = "decision-v2"


@dataclass(frozen=True)
class DecisionRuleV2Params:
    tau_present: float = 0.7  # max confidence needed to declare present
    tau_absent: float = 0.05  # every detection must stay below this to declare absent
    tau_clear: float = 1.0  # fraction of candidate locations that must be seen through
    col_min: float = 1.0  # fraction of a location's axis points seen in one view to clear it


class DecisionRuleV2:
    """Same interface as ``DecisionRule``; the absent condition is free-space evidence.

    ``absent`` requires that (the union over views of) the candidate object locations seen
    through covers at least ``tau_clear`` of them. A location where the object stands can
    never be seen through, so an unseen object keeps the answer ``inconclusive``.
    """

    def __init__(self, params: DecisionRuleV2Params | None = None, version: str | None = None):
        self.params = params or DecisionRuleV2Params()
        self.version = version or DECISION_RULE_V2_VERSION

    def cleared_fraction(self, history: Sequence[Observation]) -> float:
        from .sensing import cleared_locations

        return float(cleared_locations(history, self.params.col_min).mean())

    def absent_geometry(self, history: Sequence[Observation]) -> bool:
        return self.cleared_fraction(history) >= self.params.tau_clear - 1e-9

    def decide(self, episode: DeployableEpisode, history: Sequence[Observation]) -> DecisionOutput:
        if not history:
            raise ValueError("decision requires at least one observation")
        p = self.params
        c_max = max(o.max_confidence for o in history)
        cleared = self.cleared_fraction(history)
        features = {
            "max_confidence": c_max,
            "cleared_fraction": cleared,
            "n_views": float(len(history)),
        }
        if c_max >= p.tau_present:
            return DecisionOutput(Decision.PRESENT, confidence=c_max, features=features)
        if cleared >= p.tau_clear - 1e-9 and c_max < p.tau_absent:
            return DecisionOutput(
                Decision.ABSENT, confidence=cleared * (1.0 - c_max), features=features
            )
        return DecisionOutput(Decision.INCONCLUSIVE, confidence=0.0, features=features)
