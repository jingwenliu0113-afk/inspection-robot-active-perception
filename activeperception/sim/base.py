from __future__ import annotations

from typing import Protocol

from ..types import EpisodeGroundTruth, EpisodeSpec, Observation, Viewpoint


class ObservationSource(Protocol):
    """A world that can teleport the camera to a viewpoint and return an observation.

    ``observe`` must be memoryless with respect to the path taken (teleport
    semantics): the observation at a viewpoint depends only on (episode, viewpoint).
    ``ground_truth`` is the offline oracle pass and is never called by policies.
    """

    name: str

    def observe(self, spec: EpisodeSpec, viewpoint: Viewpoint) -> Observation: ...

    def ground_truth(self, spec: EpisodeSpec) -> EpisodeGroundTruth: ...
