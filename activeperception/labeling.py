"""World-independent mapping from GT visibility scores to the three GT states.

A world (synthetic or Gazebo) computes, for the object, a GT visibility score in
[0, 1] from the initial viewpoint and from every candidate viewpoint. This module
turns those scores into ``visible / unobservable / absent`` and ``revealable``.
Thresholds here are labeling thresholds and are frozen before the pilot.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import EpisodeGroundTruth, GroundTruthState

LABELING_VERSION = "label-v1"


@dataclass(frozen=True)
class LabelingParams:
    visible_min_score: float = 0.5


def label_episode(
    episode_id: str,
    object_present: bool,
    visibility_initial: float,
    visibility_by_viewpoint: dict[int, float],
    zone_visible_by_viewpoint: dict[int, float],
    params: LabelingParams | None = None,
) -> EpisodeGroundTruth:
    params = params or LabelingParams()
    thr = params.visible_min_score
    if not object_present:
        state = GroundTruthState.ABSENT
        revealable = False
    elif visibility_initial >= thr:
        state = GroundTruthState.VISIBLE
        revealable = True
    else:
        state = GroundTruthState.UNOBSERVABLE
        revealable = any(v >= thr for v in visibility_by_viewpoint.values())
    return EpisodeGroundTruth(
        episode_id=episode_id,
        object_present=object_present,
        state=state,
        revealable=revealable,
        visibility_initial=float(visibility_initial),
        visibility_by_viewpoint={int(k): float(v) for k, v in visibility_by_viewpoint.items()},
        zone_visible_by_viewpoint={int(k): float(v) for k, v in zone_visible_by_viewpoint.items()},
        labeling_version=LABELING_VERSION,
    )
