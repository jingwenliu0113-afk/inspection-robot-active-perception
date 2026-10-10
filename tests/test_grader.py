import pytest

from activeperception.episodes import generate_episode
from activeperception.grader import Outcome, expected_label, grade
from activeperception.types import (
    Decision,
    EpisodeGroundTruth,
    EpisodeRecord,
    GroundTruthState,
)


def _gt(state, revealable):
    return EpisodeGroundTruth(
        episode_id="x-g0000-v0",
        object_present=state != GroundTruthState.ABSENT,
        state=state,
        revealable=revealable,
        visibility_initial=0.0,
        visibility_by_viewpoint={},
        zone_visible_by_viewpoint={},
        labeling_version="t",
    )


def _rec(decision, used=2):
    spec = generate_episode("x", 0, 0)
    obs = tuple([None] * used)  # grader only counts observations
    return EpisodeRecord(
        episode_id=spec.episode_id,
        policy="p",
        budget=5,
        run_seed=0,
        viewpoint_sequence=tuple(range(-1, used - 1)),
        observations=obs,
        decision=decision,
        confidence=0.7,
        features={},
    ), spec


TABLE = [
    # state, revealable, decision, correct, false_absent, false_present
    (GroundTruthState.VISIBLE, True, Decision.PRESENT, True, False, False),
    (GroundTruthState.VISIBLE, True, Decision.ABSENT, False, True, False),
    (GroundTruthState.VISIBLE, True, Decision.INCONCLUSIVE, False, False, False),
    (GroundTruthState.UNOBSERVABLE, True, Decision.PRESENT, True, False, False),
    (GroundTruthState.UNOBSERVABLE, True, Decision.ABSENT, False, True, False),
    (GroundTruthState.UNOBSERVABLE, True, Decision.INCONCLUSIVE, False, False, False),
    (GroundTruthState.UNOBSERVABLE, False, Decision.INCONCLUSIVE, True, False, False),
    (GroundTruthState.UNOBSERVABLE, False, Decision.ABSENT, False, True, False),
    (GroundTruthState.UNOBSERVABLE, False, Decision.PRESENT, False, False, False),
    (GroundTruthState.ABSENT, False, Decision.ABSENT, True, False, False),
    (GroundTruthState.ABSENT, False, Decision.PRESENT, False, False, True),
    (GroundTruthState.ABSENT, False, Decision.INCONCLUSIVE, False, False, False),
]


@pytest.mark.parametrize("state,revealable,decision,correct,fa,fp", TABLE)
def test_grading_table(state, revealable, decision, correct, fa, fp):
    rec, spec = _rec(decision)
    out = grade(rec, _gt(state, revealable), spec)
    assert isinstance(out, Outcome)
    assert out.correct == correct
    assert out.false_absent == fa
    assert out.false_present == fp
    assert out.inconclusive == (decision == Decision.INCONCLUSIVE)
    assert out.viewpoints_used == 2
    assert out.scene_group == spec.scene_group and out.split == spec.split


def test_inconclusive_is_never_a_false_absent_or_false_present():
    for state in GroundTruthState:
        for revealable in (True, False):
            rec, spec = _rec(Decision.INCONCLUSIVE)
            out = grade(rec, _gt(state, revealable), spec)
            assert not out.false_absent and not out.false_present


def test_expected_label_mapping():
    assert expected_label(_gt(GroundTruthState.VISIBLE, True)) == Decision.PRESENT
    assert expected_label(_gt(GroundTruthState.UNOBSERVABLE, True)) == Decision.PRESENT
    assert expected_label(_gt(GroundTruthState.UNOBSERVABLE, False)) == Decision.INCONCLUSIVE
    assert expected_label(_gt(GroundTruthState.ABSENT, False)) == Decision.ABSENT


def test_grade_rejects_mismatched_ids():
    rec, spec = _rec(Decision.PRESENT)
    gt = _gt(GroundTruthState.VISIBLE, True)
    gt = EpisodeGroundTruth(**{**gt.__dict__, "episode_id": "other"})
    with pytest.raises(ValueError):
        grade(rec, gt, spec)
