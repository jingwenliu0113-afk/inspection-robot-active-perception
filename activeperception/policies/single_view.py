from __future__ import annotations

from collections.abc import Sequence

from ..types import DeployableEpisode, Observation


class SingleViewPolicy:
    """Baseline 1: only the initial viewpoint is ever observed."""

    name = "single"

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        return None

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        return None
