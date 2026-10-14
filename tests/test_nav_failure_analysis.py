"""Advanced B failure analysis: pure helpers, and the committed summary agrees with the
committed decision 019 report (it only explains those numbers, it never re-scores)."""

import json
import math
from pathlib import Path

import pytest

from activeperception.nav import failure_analysis as nfa

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "nav-failure-analysis" / "summary.json"
B2 = ROOT / "results" / "nav-b2" / "b1_report.json"


def step(target, decision, cleared, conf, refine_ok=True, nav=None):
    return {
        "target": target,
        "decision": decision,
        "cleared_fraction": cleared,
        "max_conf": conf,
        "refine_ok": refine_ok,
        **({"arrival_xy_m": nav[0], "arrival_yaw": nav[1]} if nav else {}),
    }


def test_explain_names_the_mechanism():
    tel = [step(-1, "inconclusive", 0.0, 0.0), step(3, "absent", 1.0, 0.0)]
    nav = [step(-1, "inconclusive", 0.0, 0.0), step(3, "inconclusive", 0.984, 0.0)]
    assert "seen-through" in nfa.explain(tel, nav, present=False)
    tel = [step(-1, "inconclusive", 0.0, 0.0), step(5, "present", 0.8, 0.76)]
    nav = [step(-1, "inconclusive", 0.0, 0.0), step(5, "inconclusive", 0.7, 0.39)]
    assert "detection" in nfa.explain(tel, nav, present=True)
    nav = [step(-1, "inconclusive", 0.0, 0.0), step(6, "inconclusive", 0.7, 0.39)]
    assert nfa.explain(tel, nav, present=True) == "different viewpoints chosen"


def test_nav_steps_reads_decision_input_and_scoring_arrival():
    run = {
        "steps": [
            {
                "target": -1,
                "decision": "inconclusive",
                "cleared_fraction": 0.0,
                "observation": {"max_conf": 0.1, "refine_ok": True},
            },
            {
                "target": 2,
                "decision": "present",
                "cleared_fraction": 0.5,
                "observation": {"max_conf": 0.9, "refine_ok": False},
                "nav": {"goal": {"x": 1.0, "y": 0.0, "yaw": 3.1}},
                "scoring": {"gt_base": {"x": 1.03, "y": 0.04, "yaw": -3.1}},
            },
        ]
    }
    rows = nfa.nav_steps(run)
    assert [r["target"] for r in rows] == [-1, 2]
    assert "arrival_xy_m" not in rows[0]
    assert rows[1]["arrival_xy_m"] == pytest.approx(0.05)
    assert rows[1]["arrival_yaw"] == pytest.approx(2 * math.pi - 6.2)  # wrapped across +-pi
    assert rows[1]["refine_ok"] is False


def test_attempts_counts_retries_and_unrecovered_jobs(tmp_path):
    log = tmp_path / "attempts.log"
    log.write_text(
        "t0 e1 rule-s0 attempt 1 exit 0\n"
        "t1 e2 rule-s0 attempt 1 exit 3\n"
        "t2 e2 rule-s0 attempt 2 exit 0\n"
        "t3 e3 single-s0 attempt 1 exit 3\n"
        "t4 e3 single-s0 attempt 2 exit 3\n"
        "t5 restart 1 at 2 runs\n"
    )
    a = nfa.attempts(log)
    assert a["attempts"] == 5
    assert a["exit_codes"] == {"0": 2, "3": 3}
    assert a["jobs_retried"] == 2
    assert a["jobs_never_succeeded"] == ["e3/single-s0"]


def test_cost_per_episode_sums_navigations_and_averages_random_seeds():
    class S:
        def __init__(self, eid):
            self.episode_id = eid

    navs = [
        {"episode": "a", "method": "rule", "seed": 0, "path_m": 1.0, "sim_s": 10.0},
        {"episode": "a", "method": "rule", "seed": 0, "path_m": 2.0, "sim_s": 5.0},
        {"episode": "a", "method": "random", "seed": 0, "path_m": 3.0, "sim_s": 9.0},
        {"episode": "a", "method": "random", "seed": 1, "path_m": 6.0, "sim_s": 9.0},
    ]
    c = nfa.cost_per_episode(navs, [S("a"), S("b")])
    assert c["rule_path_m"] == [3.0, 0.0]
    assert c["random_path_m"] == [3.0, 0.0]  # (3 + 6 + 0) / 3 seeds
    assert c["rule_sim_s"] == [15.0, 0.0]


def test_b0_lineage_reads_the_committed_reports():
    rows = {r["namespace"]: r for r in nfa.b0_lineage(ROOT / "results")}
    assert rows["nav-b0"]["verdict"]["C6"] is False
    assert rows["nav-b0c"]["verdict"]["C3"] is False
    assert all(rows["nav-b0d"]["verdict"].values())
    assert rows["nav-b0"]["d016_all_views_risk_episodes"] is None
    assert rows["nav-b0c"]["d016_all_views_risk_episodes"] == 0


@pytest.fixture(scope="module")
def committed():
    return json.loads(SUMMARY.read_text()), json.loads(B2.read_text())


def test_summary_matches_decision_019_report(committed):
    s, rep = committed
    nav = rep["navigation"]
    r = s["relocalization"]
    assert r["navigations"] == nav["navigations"] == 440
    assert r["corrections_used"] == nav["relocalize_corrections"]
    assert s["capture_refinement"]["failed"]["goal"] == nav["refine_failed"]
    assert s["attempts"]["attempts"] == 980 and s["attempts"]["jobs_never_succeeded"] == []
    # every teleport / Nav2 disagreement at the formal budgets is listed, none missing
    for b in (2, 3):
        for m in ("single", "random", "rule", "oracle"):
            p = rep["nav2_minus_teleport"][f"{m}@{b}"]
            rows = [
                d for d in s["discordant_formal_budgets"] if d["method"] == m and d["budget"] == b
            ]
            assert sum(d["nav2_correct"] for d in rows) == p["nav_only_correct"]
            assert sum(not d["nav2_correct"] for d in rows) == p["teleport_only_correct"]


def test_no_discordance_is_a_wrong_definitive_answer(committed):
    s, _ = committed
    for d in s["discordant_formal_budgets"]:
        assert d["nav2"] in ("inconclusive", "absent" if d["state"] == "absent" else "present")
        assert d["teleport"] in ("inconclusive", "absent" if d["state"] == "absent" else "present")


def test_cost_per_episode_reproduces_the_q4_means(committed):
    s, rep = committed
    c = s["cost_per_episode"]
    q4 = rep["claims"]["Q4_cost"]
    n = len(c["episodes"])
    assert sum(c["rule_path_m"]) / n == pytest.approx(q4["rule_path_m_per_episode"], abs=1e-3)
    assert sum(c["random_path_m"]) / n == pytest.approx(q4["random_path_m_per_episode"], abs=1e-3)
