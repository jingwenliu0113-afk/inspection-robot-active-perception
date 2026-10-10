"""Per-episode outcome grading.

Expected label per GT state (budget independent):

* visible                      -> present
* unobservable, revealable     -> present   (some candidate reveals the object)
* unobservable, not revealable -> inconclusive (the honest answer)
* absent                       -> absent

``inconclusive`` is never a false-absent and never a false-present. It is scored
as "not correct" unless it is the expected label, and reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Decision, EpisodeGroundTruth, EpisodeRecord, EpisodeSpec, GroundTruthState, Split


@dataclass(frozen=True)
class Outcome:
    episode_id: str
    scene_group: int
    split: Split
    policy: str
    budget: int
    gt_state: GroundTruthState
    revealable: bool
    expected: Decision
    decision: Decision
    confidence: float
    correct: bool
    false_absent: bool
    false_present: bool
    inconclusive: bool
    viewpoints_used: int


def expected_label(gt: EpisodeGroundTruth) -> Decision:
    if gt.state == GroundTruthState.ABSENT:
        return Decision.ABSENT
    if gt.state == GroundTruthState.VISIBLE:
        return Decision.PRESENT
    return Decision.PRESENT if gt.revealable else Decision.INCONCLUSIVE


def grade(record: EpisodeRecord, gt: EpisodeGroundTruth, spec: EpisodeSpec) -> Outcome:
    if not (record.episode_id == gt.episode_id == spec.episode_id):
        raise ValueError("record / ground truth / spec episode ids differ")
    expected = expected_label(gt)
    d = record.decision
    return Outcome(
        episode_id=record.episode_id,
        scene_group=spec.scene_group,
        split=spec.split,
        policy=record.policy,
        budget=record.budget,
        gt_state=gt.state,
        revealable=gt.revealable,
        expected=expected,
        decision=d,
        confidence=record.confidence,
        correct=d == expected,
        false_absent=gt.object_present and d == Decision.ABSENT,
        false_present=(not gt.object_present) and d == Decision.PRESENT,
        inconclusive=d == Decision.INCONCLUSIVE,
        viewpoints_used=record.viewpoints_used,
    )


def grade_all(
    records: list[EpisodeRecord],
    ground_truth: dict[str, EpisodeGroundTruth],
    specs: dict[str, EpisodeSpec],
) -> list[Outcome]:
    return [grade(r, ground_truth[r.episode_id], specs[r.episode_id]) for r in records]
