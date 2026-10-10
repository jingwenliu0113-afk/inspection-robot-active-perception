import math

from activeperception.grader import Outcome
from activeperception.metrics import (
    accuracy,
    cluster_bootstrap,
    expected_calibration_error,
    false_absent_rate,
    inconclusive_rate,
    macro_f1,
    summarize,
)
from activeperception.types import Decision, GroundTruthState, Split


def _o(group, state, expected, decision, conf=0.9, used=1):
    return Outcome(
        episode_id=f"e{group}",
        scene_group=group,
        split=Split.VAL,
        policy="p",
        budget=3,
        gt_state=state,
        revealable=True,
        expected=expected,
        decision=decision,
        confidence=conf,
        correct=expected == decision,
        false_absent=state != GroundTruthState.ABSENT and decision == Decision.ABSENT,
        false_present=state == GroundTruthState.ABSENT and decision == Decision.PRESENT,
        inconclusive=decision == Decision.INCONCLUSIVE,
        viewpoints_used=used,
    )


V, U, A = GroundTruthState.VISIBLE, GroundTruthState.UNOBSERVABLE, GroundTruthState.ABSENT
P, N, INC = Decision.PRESENT, Decision.ABSENT, Decision.INCONCLUSIVE


def test_basic_rates():
    outs = [
        _o(0, V, P, P),
        _o(1, V, P, N),
        _o(2, U, P, INC),
        _o(3, A, N, N),
        _o(4, A, N, INC),
    ]
    assert accuracy(outs) == 0.4
    assert false_absent_rate(outs) == 1 / 3  # one of three present-object episodes
    assert inconclusive_rate(outs) == 0.4
    assert accuracy([]) is None and false_absent_rate([]) is None


def test_macro_f1_known_values():
    perfect = [_o(0, V, P, P), _o(1, A, N, N)]
    assert macro_f1(perfect) == 1.0
    # present always right, absent always inconclusive: F1(present)=1, F1(absent)=0, F1(inconc)=0
    outs = [_o(0, V, P, P), _o(1, A, N, INC)]
    assert math.isclose(macro_f1(outs), 1 / 3)


def test_ece_perfect_and_imperfect():
    perfect = [_o(i, V, P, P, conf=1.0) for i in range(5)]
    assert expected_calibration_error(perfect) == 0.0
    # confidence 0.8 but all correct -> gap 0.2
    over = [_o(i, V, P, P, conf=0.8) for i in range(5)]
    assert math.isclose(expected_calibration_error(over), 0.2)
    assert expected_calibration_error([_o(0, V, P, INC)]) is None  # no definitive decisions


def test_cluster_bootstrap_contains_point_estimate_and_is_seeded():
    outs = [_o(g, V if g % 2 else A, P if g % 2 else N, P if g % 3 else INC) for g in range(20)]
    point = accuracy(outs)
    ci = cluster_bootstrap(outs, accuracy, n_boot=300, seed=1)
    assert ci is not None and ci[0] <= point <= ci[1]
    assert ci == cluster_bootstrap(outs, accuracy, n_boot=300, seed=1)
    assert cluster_bootstrap(outs[:1], accuracy) is None


def test_summarize_structure():
    outs = [_o(0, V, P, P), _o(1, U, P, INC, used=3), _o(2, A, N, N, used=3)]
    s = summarize(outs, n_boot=50)
    for k in (
        "accuracy",
        "macro_f1",
        "false_absent_rate",
        "inconclusive_rate",
        "avg_viewpoints",
        "ece",
    ):
        assert k in s and f"{k}_ci95" in s
    assert set(s["by_state"]) == {"visible", "unobservable", "absent"}
    assert s["by_state"]["unobservable"]["inconclusive_rate"] == 1.0
    assert s["n_groups"] == 3
