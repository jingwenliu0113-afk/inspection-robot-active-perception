"""The README's headline numbers are the committed results, formatted - not hand-edited claims.

If a result file and the README disagree, the README is wrong (results are sealed)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def num(x: float, sign: bool = False) -> str:
    """README style: 3 decimals, true minus sign (U+2212)."""
    s = f"{x:+.3f}" if sign else f"{x:.3f}"
    return s.replace("-", "−")


def ci(r: dict, mean: str = "mean", sign: bool = True) -> str:
    return f"{num(r[mean], sign)} [{num(r['ci95'][0])}, {num(r['ci95'][1])}]"


def test_core_v1_test_numbers():
    s = load("results/test-v1/report.json")["summary"]
    for key in ("single@1", "random@2", "random@3", "rule@2", "rule@3", "oracle@2"):
        assert num(s[key]["accuracy"]) in README, key
    assert f"{s['rule@3']['avg_viewpoints']:.2f} 個視角" in README
    assert all(s[f"rule@{b}"]["false_absent_rate"] == 0 for b in (2, 3, 5))


def test_holdout_v1_v2_numbers():
    r = load("results/holdout/report.json")
    v1, v2 = r["v1"]["summary"], r["v2"]["summary"]
    assert f"0.683 → **{num(v2['rule@2']['accuracy'])}**" in README
    assert num(v1["rule@2"]["accuracy"]) == "0.683"
    abl = r["claims"]["ablation"]["2"]
    assert ci(abl["decision_effect(abl_rule - v1_rule)"], "diff") in README
    assert ci(abl["policy_effect(v2_rule - abl_rule)"], "diff") in README
    # "all methods, all budgets: false absent 0" (v2)
    assert all(v["false_absent_rate"] == 0 for v in v2.values())


def test_nav_b2_numbers():
    rep = load("results/nav-b2/b1_report.json")
    t, n = rep["teleport"], rep["nav2"]
    assert f"{num(t['rule@2']['accuracy'])} / **{num(n['rule@2']['accuracy'])}**" in README
    assert f"{num(t['random@2']['accuracy'])} / {num(n['random@2']['accuracy'])}" in README
    c = rep["claims"]
    for key in ("rule-random@2", "rule-random@3"):
        assert ci(c["Q3_active_vs_baselines_nav"][key]) in README, key
    lows = [r["ci95"][0] for r in c["Q2_nav_minus_teleport"].values()]
    assert f"最低 CI 下界 {num(min(lows))}" in README
    # Q1: every method, every budget
    assert all(
        v[k] == 0 for v in n.values() for k in ("false_absent", "false_present", "geometric_risk")
    )
    nav = rep["navigation"]
    assert nav["navigations"] == 440 and nav["path_success_rate"] == 1.0
    assert nav["collisions"] == 0 and nav["timeouts"] == 0
    assert "440 次全部準確到點" in README


def test_failed_gates_stay_reported():
    for phrase in (
        "**未通過**（0.028 / 0.032）",
        "**budget 2 未通過**（0.043 [0.020, 0.070]）",
        "**不是**選視角策略",
    ):
        assert phrase in README


def test_decision_thresholds_match_the_frozen_configs():
    from activeperception.frozen import DECISION_V1
    from activeperception.frozen_v2 import DECISION_V2

    assert f"且所有 confidence < {DECISION_V1.tau_absent}" in README  # decision-v1
    assert f"**看穿**，且所有 confidence < {DECISION_V2.tau_absent}" in README  # decision-v2
    assert f"confidence ≥ {DECISION_V2.tau_present}" in README
