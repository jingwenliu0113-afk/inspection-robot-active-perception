"""Failure analysis reads the committed results only and reports datasets separately."""

import json
from pathlib import Path

import pytest

from activeperception import failure_analysis as fa

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "failure-analysis" / "summary.json"


def row(eid, correct, method="rule", state="absent", decision=None, seed=0, config="v2"):
    decision = decision or ("absent" if correct else "inconclusive")
    return {
        "episode_id": eid,
        "correct": correct,
        "method": method,
        "gt_state": state,
        "decision": decision,
        "inconclusive": decision == "inconclusive",
        "false_absent": state != "absent" and decision == "absent",
        "false_present": state == "absent" and decision == "present",
        "seed": seed,
        "config": config,
        "budget": 2,
    }


def test_attribution_splits_policy_gap_from_structural():
    rule = [row("a", True), row("b", False), row("c", False, state="unobservable")]
    oracle = [row("a", True), row("b", True), row("c", False, state="unobservable")]
    a = fa.attribution(rule, [{**r, "method": "oracle"} for r in oracle])
    assert (a["rule_failures"], a["policy_gap"], a["structural"]) == (2, 1, 1)
    assert a["policy_gap_episodes"] == ["b"]
    assert a["structural_by_state"] == {"unobservable": 1}


def test_transitions_count_fixed_and_broken():
    a = [row("a", True), row("b", False), row("c", True), row("d", False)]
    b = [row("a", True), row("b", True), row("c", False), row("d", False)]
    t = fa.transitions(a, b)
    assert t == {
        "both_correct": 1,
        "both_wrong": 1,
        "fixed": 1,
        "broken": 1,
        "broken_episodes": ["c"],
    }


def test_error_matrix_sums_seeds_and_flags_false_absent():
    rows = [
        row("a", False, method="random", state="unobservable", decision="absent", seed=0),
        row("a", True, method="random", state="unobservable", decision="present", seed=1),
    ]
    m = fa.error_matrix(rows)
    assert m["n_seeds"] == 2 and m["n"] == 1
    assert m["false_absent"] == 1 and m["wrong_definitive"] == 1
    assert m["decisions_by_state"]["unobservable"] == {"absent": 1, "present": 1}


@pytest.mark.skipif(not SUMMARY.exists(), reason="summary not generated")
def test_committed_summary_reproduces_from_committed_results():
    want = json.loads(SUMMARY.read_text())
    want.pop("dev_rule_nbv_v2_ties", None)  # needs the local frame store
    got = json.loads(json.dumps(fa.analyze(ROOT), sort_keys=True))
    assert got == want


@pytest.mark.skipif(not SUMMARY.exists(), reason="summary not generated")
def test_headline_findings():
    s = json.loads(SUMMARY.read_text())
    d = s["datasets"]
    # v2 residual failures are all attributable to viewpoint choice and never a wrong answer
    for b in ("2", "3"):
        a = d["holdout/v2"]["rule"][b]["attribution"]
        assert a["structural"] == 0 and a["policy_gap_wrong_definitive"] == 0
        assert d["holdout/v2"]["errors"][b]["rule"]["wrong_definitive"] == 0
    # the decision rule alone never turns a correct v1 answer into a failure
    for b in ("2", "3"):
        assert s["holdout_paired"][b]["decision_effect_v1_rule_to_ablation"]["broken"] == 0
    # v2 has no false absent at all; v1 Random has one on each formal split
    assert d["holdout/v2"]["false_absent_cases"] == []
    assert {c["episode_id"] for c in d["test/v1"]["false_absent_cases"]} == {"core-g0103-v0"}
    assert {c["episode_id"] for c in d["holdout/v1"]["false_absent_cases"]} == {"holdout-g0046-v2"}
