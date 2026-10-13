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
