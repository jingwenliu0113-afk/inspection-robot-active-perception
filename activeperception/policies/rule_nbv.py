"""Rule-based next-best-view (v0, pilot version; frozen before the formal test).

Allowed inputs (SPEC §6): detector confidence, bbox area, observation history,
viewpoint geometry, coverage proxy. The rule scores each unvisited candidate with

    score = w_novelty * novelty + w_attraction * attraction + w_unobstructed * unobstructed

* novelty: normalised angular distance from the nearest visited viewpoint
  (push towards unseen bearings -> coverage).
* attraction: if the strongest detection so far is a *weak* one (above
  ``tau_weak`` but not yet decisive), prefer candidates about
  ``attraction_target`` radians away from that viewpoint's bearing: close enough
  to keep the object in view, far enough to look around the occluder.
* unobstructed: kernel-weighted average of the sensor-derived
  ``zone_visible_fraction`` of visited viewpoints near the candidate's bearing
  (avoid bearings that were seen to be blocked). Prior 0.5 when nothing nearby.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..geometry import angular_distance
from ..types import DeployableEpisode, Observation
from .base import unvisited_candidates

RULE_NBV_VERSION = "rule-nbv-v0"


@dataclass(frozen=True)
class RuleNBVParams:
    w_novelty: float = 1.0
    w_attraction: float = 1.0
    w_unobstructed: float = 0.5
    tau_weak: float = 0.15
    attraction_target: float = math.radians(45.0)
    attraction_sigma: float = math.radians(30.0)
    neighbour_sigma: float = math.radians(40.0)
    unobstructed_prior: float = 0.5


class RuleNBVPolicy:
    name = "rule"
    version = RULE_NBV_VERSION

    def __init__(self, params: RuleNBVParams | None = None):
        self.params = params or RuleNBVParams()

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        return None

    def score(
        self, episode: DeployableEpisode, history: Sequence[Observation], azimuth: float
    ) -> float:
        p = self.params
        novelty = min(angular_distance(azimuth, o.viewpoint.azimuth) for o in history) / math.pi
        best = max(history, key=lambda o: o.max_confidence)
        attraction = 0.0
        if best.max_confidence >= p.tau_weak:
            d = angular_distance(azimuth, best.viewpoint.azimuth) - p.attraction_target
            attraction = math.exp(-(d * d) / (2.0 * p.attraction_sigma**2))
        wsum = 0.0
        acc = 0.0
        for o in history:
            d = angular_distance(azimuth, o.viewpoint.azimuth)
            w = math.exp(-(d * d) / (2.0 * p.neighbour_sigma**2))
            wsum += w
            acc += w * o.zone_visible_fraction
        unobstructed = acc / wsum if wsum > 1e-6 else p.unobstructed_prior
        return p.w_novelty * novelty + p.w_attraction * attraction + p.w_unobstructed * unobstructed

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        cands = unvisited_candidates(episode, history)
        if not cands:
            return None
        scored = sorted((-self.score(episode, history, vp.azimuth), vp.id) for vp in cands)
        return scored[0][1]
