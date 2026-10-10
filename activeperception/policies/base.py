from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..types import DeployableEpisode, Observation, Viewpoint


class Policy(Protocol):
    """Next-best-view policy.

    ``select_next`` receives only the deployable episode view and the observation
    history. Returning ``None`` means "stop early". The harness enforces the
    budget and rejects revisits / unknown ids.
    """

    name: str

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None: ...

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None: ...


def unvisited_candidates(
    episode: DeployableEpisode, history: Sequence[Observation]
) -> list[Viewpoint]:
    visited = {o.viewpoint_id for o in history}
    return [vp for vp in episode.candidate_viewpoints if vp.id not in visited]
