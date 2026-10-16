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


def test_r0a_numbers():
    from activeperception.r0a import _pct

    rep = load("results/r0a/report.json")
    c, cam = rep["criteria"], rep["summary"]["camera"]
    assert _pct(c["A1_clear_localized_recall"]) in README
    assert c["A1_clear_localized_recall"]["pass"] and not c["A2_false_present"]["pass"]
    assert _pct(c["A2_false_present"]) in README
    assert f"{100 * c['A3_absent_blocked']['rate']:.1f}%" in README
    miss = cam["positives"]["main"]["complete_miss"]
    assert miss["k"] == 0 and f"0 / {miss['n']}" in README
    assert "R0a 為真實照片" in README  # never presented as simulation or as a robot result


def test_r0b_numbers():
    rep = load("results/r0b/report.json")
    assert (
        rep["criteria"]["R1_primary_D1_L1_b"]["pass"]
        and rep["criteria"]["R2_stress_D2_L2_b"]["pass"]
    )
    by = {tuple(r["condition"].values()): r for r in rep["results"]}
    primary = by[("D1", "L1", "b")]
    occ = primary["occupied_false_clearance"]
    assert occ["views"] == 0 and f"0 / {occ['present_views']:,}" in README
    noisy_b = [r for (d, _, pipe), r in by.items() if pipe == "b" and d != "D0"]
    absent5 = [round(r["summary"]["rule@5"]["accuracy_by_state"]["absent"] * 80) for r in noisy_b]
    assert f"{min(absent5)}–{max(absent5)} / 80" in README
    p95 = [r["pose_error_used"]["xy_p95"] * 100 for r in noisy_b]
    assert f"p95 {int(min(p95))}–{round(max(p95))} cm" in README
    # pipeline (a) loses the geometric guarantee under every error, but no false absent occurs
    a_noisy = [r for (d, q, pipe), r in by.items() if pipe == "a" and (d, q) != ("D0", "P0")]
    assert all(r["all_views_geometric_risk"] for r in a_noisy)
    assert all(v["false_absent"] == 0 for r in rep["results"] for v in r["summary"].values())


def test_v3_formal_numbers():
    rep = load("results/v3/report.json")
    ver, res = rep["verdicts"], rep["results"]
    assert ver["V1"]["pass"] and ver["V2"]["pass"] and ver["V3"]["pass"] and ver["V5"]["pass"]
    assert not ver["V4"]["pass"] and "V4 **未通過**" in README  # the failure stays visible
    typ3, typ2 = res["v3:D1xL1:v3"], res["v3:D1xL1:v2"]
    acc = " / ".join(f"{typ3['summary'][f'rule@{b}']['accuracy']:.3f}" for b in (2, 3, 5))
    assert f"**{acc}**" in README
    a2 = typ2["summary"]["rule@5"]["accuracy_by_state"]["absent"]
    assert f"absent@5 {a2:.3f} → **1.000**" in README
    fp = [res[f"v3-dx:{c}:v2"]["false_present"] for c in ("D0xP0", "D1xL1")]
    assert f"{fp[0]:,} / {fp[1]:,}" in README
    assert all(res[f"v3-dx:{c}:v3"]["false_present"] == 0 for c in ("D0xP0", "D1xL1"))
    stress = res["v3:D2xL2:v3"]["occupied_false_clearance"]
    assert f"{stress['views']} / {stress['present_views']:,}" in README
    d = rep["v3_minus_v2"]["v3:D1xL1"]["rule@3"]
    assert ci(d) in README
    assert all(c["false_absent"] == 0 for c in res.values())  # never "absent" when present


def test_b_depth_numbers():
    cmp = load("results/depthnoise/comparison.json")["cameras"]
    assert f"{-100 * cmp['D435']['bias']['worst']:.2f}%" in README
    assert cmp["D435"]["bias"]["sign"].startswith("符號未涵蓋")
    assert all(c["correlation"]["verdict"] == "相關更長" for c in cmp.values())


def test_detector_v2_formal_numbers():
    rep = load("results/detv2/report.json")
    ver, real = rep["verdicts"], rep["real"]
    assert not ver["T1"]["pass"] and "T1 **未通過**" in README  # the failure stays visible
    assert ver["T2"]["pass"] and ver["T3"]["pass"] and ver["T4"]["pass"]
    v1, v2 = real["v1"]["neg:verified"]["present"], real["v2"]["neg:verified"]["present"]
    assert f"{v1['k']} / {v1['n']} = {100 * v1['rate']:.1f}%" in README
    assert f"**{v2['k']} / {v2['n']} = {100 * v2['rate']:.1f}%**" in README
    lo, hi = v2["ci95"]
    assert f"[{100 * lo:.1f}%, {100 * hi:.1f}%]" in README
    pv = real["paired"]["neg:verified"]
    assert f"修好 {pv['fixed']} 張、弄壞 {pv['broken']} 張" in README
    m = load("results/detv2/t5-misses.json")
    assert f"{m['v1_missed']} → {m['v2_missed']} / {m['n_positives']}" in README
    sel = load("results/detv2-dev/selection.json")
    assert sel["selected"] == "base" and "選 `base`" in README


def test_v4_and_d3_formal_numbers():
    rep = load("results/v4/report.json")
    ver, res = rep["verdicts"], rep["results"]
    assert all(ver[k]["pass"] for k in ("W1", "W2", "W3", "W4", "W5", "W6", "D1"))
    v3s, v4s = res["v4:D2xL2:v3"], res["v4:D2xL2:v4"]
    assert (
        v3s["occupied_false_clearance"]["views"] == 1
        and v4s["occupied_false_clearance"]["views"] == 0
    )
    for cond in ("D2xL2", "D3xL1"):
        e3 = res[f"v4:{cond}:v3"]["exceed"]["refined_ok"]
        e4 = res[f"v4:{cond}:v4"]["exceed"]["refined_ok"]
        assert f"{e3} → **{e4}**" in README and f"{e4} / {e3}" in README
    a1 = res["v4:D1xL1:v4"]["summary"]["rule@5"]["accuracy_by_state"]["absent"]
    assert f"{round(a1 * 80)} / 80 = {a1:.3f}" in README
    d3 = [res["v4:D3xL1:v3"], res["v4:D3xL1:v4"]]
    absent = [c["summary"]["rule@5"]["accuracy_by_state"]["absent"] for c in d3]
    assert f"absent@5 {absent[0]:.3f} → {absent[1]:.3f}" in README
    d = rep["v4_minus_v3"]["v4:D1xL1"]["rule@3"]
    assert f"budget 3 {d['mean']:+.3f}".replace("-", "−") in README.replace("-", "−")
    assert ci(d).replace("-", "−") in README.replace("-", "−")
    assert all(c["false_absent"] == 0 for c in res.values())


def test_v5_formal_numbers():
    rep = load("results/v5/report.json")
    ver, res = rep["verdicts"], rep["results"]
    assert all(ver[k]["pass"] for k in ("X1", "X2", "X3", "X4"))
    assert all(v3_safe(c) for k, c in res.items() if k.endswith(":v5"))
    for cond in ("D2xL2", "D3xL1"):
        r = ver["X2"]["rule_b3_v5_minus_v4"][cond]
        assert f"{cond.replace('x', '×')} {num(r['mean'], True)}" in README
        assert f"[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]" in README
        b3 = [res[f"v5:{cond}:{p}"]["summary"]["rule@3"]["accuracy"] for p in ("v4", "v5")]
        assert f"{num(b3[0])} → **{num(b3[1])}**" in README
    for k in ("v5:D2xL2", "v5:D3xL1", "v5-dx:D3xL1"):
        a = [
            res[f"{k}:{p}"]["summary"]["rule@5"]["accuracy_by_state"]["absent"]
            for p in ("v4", "v5")
        ]
        assert f"{num(a[0])} → {num(a[1])}" in README, k
    d3p0 = res["v5:D3xP0:v5"]["summary"]["rule@5"]["accuracy_by_state"]["absent"]
    assert f"D3×P0 absent@5 仍只有 {num(d3p0)}" in README
    only_v4 = sum(
        per[f"v5@{b}"]["v4_only_correct"]
        for per in rep["paired_minus_v4"].values()
        for b in (2, 3, 5)
    )
    assert f"{only_v4} 集 absent" in README and only_v4 == 7
    assert all(ver["R2"]["safe"].values())  # "不包住的版本也全部安全"


def v3_safe(c: dict) -> bool:
    return (
        c["false_absent"] == 0
        and c["false_present"] == 0
        and c["geometric_risk"] == 0
        and not c["all_views_geometric_risk"]
        and c["occupied_false_clearance"]["views"] == 0
    )
