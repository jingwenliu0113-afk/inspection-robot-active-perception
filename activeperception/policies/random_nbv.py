from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ..episodes import stable_seed
from ..types import DeployableEpisode, Observation
from .base import unvisited_candidates


class RandomNBVPolicy:
    """Baseline 2: uniformly random unvisited candidate (seeded per run and episode)."""

    name = "random"

    def __init__(self) -> None:
        self._rng = np.random.default_rng(0)

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        self._rng = np.random.default_rng(stable_seed("random-nbv", run_seed, episode.episode_id))

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        ids = sorted(vp.id for vp in unvisited_candidates(episode, history))
        if not ids:
            return None
        return int(self._rng.choice(ids))
