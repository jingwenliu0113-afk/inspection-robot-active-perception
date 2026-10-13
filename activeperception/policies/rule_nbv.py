"""Rule-based next-best-view.

Allowed inputs (SPEC §6): detector confidence, bbox area, observation history, viewpoint
geometry, coverage proxy. Each unvisited candidate is scored with

    score = w_coverage * coverage_gain + w_visibility * predicted_visibility
          + w_novelty * novelty + w_attraction * attraction + w_unobstructed * unobstructed

* coverage_gain (v1): 1 if the candidate's sector - the same sectors the shared decision
  rule counts - has no effective view yet.
* predicted_visibility (v1): fraction of zone samples the candidate would see past the
  obstacle height map accumulated from the depth of visited views (decision 008).
* novelty: normalised angular distance from the nearest visited viewpoint.
* attraction: if the strongest detection so far is a *weak* one (above ``tau_weak`` but
  not decisive), prefer candidates about ``attraction_target`` radians away from that
  viewpoint's bearing: close enough to keep the object in view, far enough to look
  around the occluder.
* unobstructed (v0): kernel-weighted average of the ``zone_visible_fraction`` of visited
  viewpoints near the candidate's bearing; prior 0.5 when nothing is nearby.

Highest score wins; ties go to the lowest candidate id. Defaults are the v0 weights; the
frozen v1 configuration lives in ``activeperception.frozen`` (decision 009).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..decision import DecisionRuleParams, sector_of
from ..geometry import angular_distance
from ..sensing import merge_obstacle_cells, predicted_zone_visibility
from ..types import DeployableEpisode, Observation
from .base import unvisited_candidates

RULE_NBV_VERSION = "rule-nbv-v0"


@dataclass(frozen=True)
class RuleNBVParams:
    w_coverage: float = 0.0
    w_visibility: float = 0.0
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

    def __init__(
        self,
        params: RuleNBVParams | None = None,
        decision_params: DecisionRuleParams | None = None,
        visibility_cache: dict | None = None,
        version: str | None = None,
    ):
        """``visibility_cache`` may be shared across policy instances that run on the SAME
        world (e.g. a parameter sweep); keys are (episode, visited ids, candidate)."""
        self.params = params or RuleNBVParams()
        self.dp = decision_params or DecisionRuleParams()
        self.version = version or RULE_NBV_VERSION
        self._shared = visibility_cache is not None
        self._vis_cache: dict[tuple, float] = {} if visibility_cache is None else visibility_cache

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        if not self._shared:
            self._vis_cache.clear()

    def features(
        self,
        episode: DeployableEpisode,
        history: Sequence[Observation],
        vp,
        height_map: dict | None = None,
    ) -> dict[str, float]:
        p = self.params
        az = vp.azimuth
        covered = {
            sector_of(o.viewpoint.azimuth, self.dp.n_sectors)
            for o in history
            if o.zone_visible_fraction >= self.dp.effective_zone_fraction
        }
        feats = {
            "coverage_gain": float(sector_of(az, self.dp.n_sectors) not in covered),
            "novelty": min(angular_distance(az, o.viewpoint.azimuth) for o in history) / math.pi,
        }
        best = max(history, key=lambda o: o.max_confidence)
        attraction = 0.0
        if p.tau_weak <= best.max_confidence:
            d = angular_distance(az, best.viewpoint.azimuth) - p.attraction_target
            attraction = math.exp(-(d * d) / (2.0 * p.attraction_sigma**2))
        feats["attraction"] = attraction
        wsum = acc = 0.0
        for o in history:
            d = angular_distance(az, o.viewpoint.azimuth)
            w = math.exp(-(d * d) / (2.0 * p.neighbour_sigma**2))
            wsum += w
            acc += w * o.zone_visible_fraction
        feats["unobstructed"] = acc / wsum if wsum > 1e-6 else p.unobstructed_prior
        if p.w_visibility:
            key = (episode.episode_id, tuple(o.viewpoint_id for o in history), vp.id)
            if key not in self._vis_cache:
                if height_map is None:
                    height_map = merge_obstacle_cells(o.obstacle_cells for o in history)
                self._vis_cache[key] = predicted_zone_visibility(
                    height_map, episode.camera, vp.pose, episode.zone
                )
            feats["predicted_visibility"] = self._vis_cache[key]
        return feats

    def score(
        self,
        episode: DeployableEpisode,
        history: Sequence[Observation],
        vp,
        height_map: dict | None = None,
    ) -> float:
        p = self.params
        f = self.features(episode, history, vp, height_map)
        return (
            p.w_coverage * f["coverage_gain"]
            + p.w_visibility * f.get("predicted_visibility", 0.0)
            + p.w_novelty * f["novelty"]
            + p.w_attraction * f["attraction"]
            + p.w_unobstructed * f["unobstructed"]
        )

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        cands = unvisited_candidates(episode, history)
        if not cands:
            return None
        hmap = (
            merge_obstacle_cells(o.obstacle_cells for o in history)
            if self.params.w_visibility
            else None
        )
        scored = sorted((-self.score(episode, history, vp, hmap), vp.id) for vp in cands)
        return scored[0][1]
