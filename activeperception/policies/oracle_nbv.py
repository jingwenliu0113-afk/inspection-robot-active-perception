"""Oracle NBV: upper bound only. Reads simulator ground truth; never deployable."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..decision import DecisionRuleParams, sector_of
from ..geometry import angular_distance
from ..types import DeployableEpisode, EpisodeGroundTruth, Observation
from .base import unvisited_candidates


class OracleNBVPolicy:
    name = "oracle"

    def __init__(
        self,
        gt_lookup: Callable[[str], EpisodeGroundTruth],
        decision_params: DecisionRuleParams | None = None,
    ):
        self._gt_lookup = gt_lookup
        self._dp = decision_params or DecisionRuleParams()

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        return None

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        cands = unvisited_candidates(episode, history)
        if not cands:
            return None
        gt = self._gt_lookup(episode.episode_id)
        if gt.object_present:
            # best GT visibility of the object; tie -> lowest id
            return sorted((-gt.visibility_by_viewpoint.get(vp.id, 0.0), vp.id) for vp in cands)[0][
                1
            ]
        # absent: maximise coverage -> an unobstructed view in a not-yet-covered sector
        covered = {
            sector_of(o.viewpoint.azimuth, self._dp.n_sectors)
            for o in history
            if o.zone_visible_fraction >= self._dp.effective_zone_fraction
        }
        ranked = []
        for vp in cands:
            zone_ok = (
                gt.zone_visible_by_viewpoint.get(vp.id, 0.0) >= self._dp.effective_zone_fraction
            )
            new_sector = sector_of(vp.azimuth, self._dp.n_sectors) not in covered
            novelty = min(angular_distance(vp.azimuth, o.viewpoint.azimuth) for o in history)
            ranked.append((-(int(zone_ok) * 2 + int(new_sector)), -novelty, vp.id))
        return sorted(ranked)[0][2]
