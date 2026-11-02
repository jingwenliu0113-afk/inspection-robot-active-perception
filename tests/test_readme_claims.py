"""The README's headline numbers are the committed results, formatted - not hand-edited claims.

If a result file and a README disagree, the README is wrong (results are sealed). ``README`` is the
Traditional Chinese version (README.zh-TW.md, the full record); the English README.md is checked
against the same files in ``test_english_readme_*``."""

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.zh-TW.md").read_text()
README_EN = (ROOT / "README.md").read_text()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def num(x: float, sign: bool = False) -> str:
    """README style: 3 decimals, true minus sign (U+2212)."""
    s = f"{x:+.3f}" if sign else f"{x:.3f}"
    return s.replace("-", "−")


def ci(r: dict, mean: str = "mean", sign: bool = True) -> str:
    return f"{num(r[mean], sign)} [{num(r['ci95'][0])}, {num(r['ci95'][1])}]"


def rule_of_three(n: int) -> str:
    """0 events in n trials: the one-sided 95% upper bound is about 3/n, as the READMEs print it."""
    pct = 300 / n
    if 30000 % n:
        return f"3/{n} ≈ {pct:.1f}%"
    exact = f"{pct:.2f}".rstrip("0")
    return f"3/{n} = {exact}{'0' if exact.endswith('.') else ''}%"


def object_present(namespace: str, split: str | None = None) -> tuple[int, int]:
    """(object-present episodes, scene groups they belong to) in a committed episode set."""
    eps = [
        e
        for e in load(f"data/episodes/gazebo-{namespace}.json")["episodes"]
        if e["ground_truth"]["object_present"] and split in (None, e["spec"]["split"])
    ]
    return len(eps), len({e["spec"]["scene_group"] for e in eps})


def test_core_v1_test_numbers():
    t = load("results/test-v1/report.json")
    s = t["summary"]
    for key in ("single@1", "random@2", "random@3", "rule@2", "rule@3", "oracle@2"):
        assert num(s[key]["accuracy"]) in README, key
    assert f"{s['rule@3']['avg_viewpoints']:.2f} 個視角" in README
    assert all(s[f"rule@{b}"]["false_absent_rate"] == 0 for b in (2, 3, 5))
    # Single's 0.202 is the one-view floor; all four methods score it at budget 1, where each has
    # only the initial view (decision 002, budget rule); Single stays in the pre-registered tests
    floor = {s[f"{m}@1"]["accuracy"] for m in ("single", "random", "rule", "oracle")}
    assert floor == {s["single@1"]["accuracy"]}
    assert f"Single View 的 **{num(s['single@1']['accuracy'])}** 是單一視角的結構性下限" in README
    assert "budget 1 時每個方法都只有初始視角" in README
    assert "仍保留在事先登錄的比較中" in README and "不是對手" not in README
    un, ab = t["by_state"]["unobservable:single@1"], t["by_state"]["absent:single@1"]
    assert ab["inconclusive_rate"] == 1.0
    k = round(un["inconclusive_rate"] * un["n"])
    single = f"{ab['n']} 集 absent 全部、{un['n']} 集 unobservable 中的 {k} 集都是 `inconclusive`"
    assert single in README


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
    # the core-test 0.996 sits next to the same v1 on holdout
    lo, hi = v1["rule@3"]["accuracy_ci95"]
    held = f"{num(v1['rule@3']['accuracy'])} [{num(lo)}, {num(hi)}]"
    assert held == "0.968 [0.945, 0.988]" and held in README and held in README_EN
    # ECE drop of definite decisions, with the note that it is mostly a change of definition
    ece1 = [v["ece"] for k, v in v1.items() if not k.startswith("single") and not k.endswith("@1")]
    ece2 = [v["ece"] for v in v2.values()]
    drop = f"{min(ece1):.2f}–{max(ece1):.2f}"
    bound = f"{math.ceil(max(ece2) * 1e4) / 1e4:.4f}"  # an upper bound, so rounded up
    assert f"ECE 從 {drop} 降到 ≤ {bound}" in README
    assert f"ECE ≤ {bound}，但這主要是定義的改變" in README
    assert "下降主要來自 absent confidence 的定義改變" in README
    assert f"drops from {drop} to ≤ {bound}" in README_EN
    assert "This drop mainly comes from a changed" in README_EN
    for text in (README, README_EN):
        assert not re.search(r"≤ 0\.008(?!\d)", text)  # rounded down, below the v2 maximum


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
    # 960 = method runs (Single never moves); the collision count is over the 440 navigations
    runs = sum(n[f"{m}@5"]["n"] for m in ("single", "random", "rule", "oracle"))
    assert runs == 960 and n["single@5"]["avg_views"] == 1.0
    assert f"{nav['navigations']} 次導航碰撞 **{nav['collisions']}**" in README
    assert f"（共 {runs} 次方法執行，包括從不移動的 Single）" in README
    assert "960 次閉迴路" not in README and "真正用 Nav2" not in README
    # every Nav2 result is from Gazebo: no wording that reads as a physical robot
    assert not any(w in README for w in ("真正導航", "實際導航", "實際開到"))


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
    assert "R0a、A 為真實照片" in README  # never presented as simulation or as a robot result


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
    # one count per condition, summed over 4 methods x budgets 1-5 (Random: 3 seeds), not a ratio
    for c, total in zip(("D0xP0", "D1xL1"), fp, strict=True):
        summary = res[f"v3-dx:{c}:v2"]["summary"]
        assert total == sum(v["false_present"] for v in summary.values())
        assert {k.split("@")[0] for k in summary} == {"single", "random", "rule", "oracle"}
        assert {int(k.split("@")[1]) for k in summary} == {1, 2, 3, 4, 5}
    assert f"D0×P0 {fp[0]:,} 次、D1×L1 {fp[1]:,} 次" in README
    rule3 = res["v3-dx:D1xL1:v2"]["summary"]["rule@3"]["false_present"]
    episodes = load("data/episodes/gazebo-v3-dx.json")["episodes"]
    absent = sum(not e["ground_truth"]["object_present"] for e in episodes)
    assert f"{absent} 集 absent 中 {rule3} 集 → **0**" in README
    assert f"{rule3} of {absent} absent episodes → **0**" in README_EN
    assert f"{fp[0]:,} in D0×P0, {fp[1]:,} in D1×L1" in README_EN
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


def test_english_readme_numbers():
    """The English README quotes the same committed results."""
    s = load("results/test-v1/report.json")["summary"]
    for key in ("single@1", "random@3", "rule@3"):
        assert f"**{num(s[key]['accuracy'])}**" in README_EN, key
    assert f"{s['rule@3']['avg_viewpoints']:.2f} views" in README_EN
    r = load("results/holdout/report.json")
    assert f"0.683 → **{num(r['v2']['summary']['rule@2']['accuracy'])}**" in README_EN
    abl = r["claims"]["ablation"]["2"]
    assert ci(abl["decision_effect(abl_rule - v1_rule)"], "diff") in README_EN
    assert ci(abl["policy_effect(v2_rule - abl_rule)"], "diff") in README_EN
    b2 = load("results/nav-b2/b1_report.json")
    c = b2["claims"]["Q3_active_vs_baselines_nav"]
    assert f"**{ci(c['rule-random@2'])}**" in README_EN
    nav = b2["navigation"]
    runs = sum(b2["nav2"][f"{m}@5"]["n"] for m in ("single", "random", "rule", "oracle"))
    assert f"**{nav['navigations']}** navigations, **{nav['collisions']}**" in README_EN
    assert f"({runs} method runs in total, including Single, which never moves)" in README_EN
    assert "closed-loop runs" not in README_EN and "real Nav2" not in README_EN
    assert "real navigation" not in README_EN
    assert f"Single View's **{num(s['single@1']['accuracy'])}** is a structural floor" in README_EN
    assert "at budget 1, where every method has only the initial view, all four score" in README_EN
    assert "it stays in the pre-registered comparisons" in README_EN
    assert "not a competitor" not in README_EN and "competing result" not in README_EN
    a = load("results/r0a/report.json")["criteria"]
    from activeperception.r0a import _pct

    assert _pct(a["A1_clear_localized_recall"]) in README_EN
    assert _pct(a["A2_false_present"]) in README_EN
    v5 = load("results/v5/report.json")["verdicts"]["X2"]["rule_b3_v5_minus_v4"]
    for cond in ("D2xL2", "D3xL1"):
        r5 = v5[cond]
        assert f"{num(r5['mean'], True)} [{r5['ci95'][0]:.3f}, {r5['ci95'][1]:.3f}]" in README_EN
    d = load("results/detv2/report.json")["real"]
    v1, v2 = d["v1"]["neg:verified"]["present"], d["v2"]["neg:verified"]["present"]
    assert f"{v1['k']} / {v1['n']} = {100 * v1['rate']:.1f}%" in README_EN
    assert f"**{v2['k']} / {v2['n']} = {100 * v2['rate']:.1f}%**" in README_EN


def test_english_readme_keeps_failures_and_validation_scope():
    for phrase in (
        "**fail** (0.028 / 0.032)",
        "**fail at budget 2** (0.043 [0.020, 0.070])",
        "**not** a better view-selection policy",
        "V4 stress D2×L2",
        "T1 false present on hard negatives ≤ 1%",
        "failed the pre-registered per-view safety gate",
    ):
        assert phrase in README_EN, phrase
    # real photos tested the detector only; the full system never ran on hardware
    assert "the *detector alone* was tested on real internet photos" in README_EN
    assert "the full system has **not** run on physical hardware" in README_EN


def test_zero_counts_carry_upper_bounds():
    """A false-absent 0 is an observed count: both READMEs give its rule-of-three bound, per
    object-present episode and per scene group (the two object-present episodes of a group are
    correlated)."""
    t, h = load("results/test-v1/report.json"), load("results/holdout/report.json")
    b2 = load("results/nav-b2/b1_report.json")
    sets = {
        "core": object_present("core", "test"),
        "holdout": object_present("holdout"),
        "nav-b2": object_present("nav-b2"),
    }
    by, hby = t["by_state"], h["v1"]["by_state"]
    assert sets["core"] == (
        by["visible:rule@3"]["n"] + by["unobservable:rule@3"]["n"],
        t["n_groups"],
    )
    assert sets["holdout"] == (
        hby["visible:rule@3"]["n"] + hby["unobservable:rule@3"]["n"],
        h["n_groups"],
    )
    assert sets["nav-b2"][0] == b2["states"]["visible"] + b2["states"]["unobservable"]
    for ns in ("r0b", "v3", "v3-dx", "v4", "v4-dx", "v5", "v5-dx"):
        assert object_present(ns) == sets["nav-b2"], ns  # each simulated-error set: 80 in 40 groups
    for n_episodes, n_groups in sets.values():
        for text in (README, README_EN):
            assert rule_of_three(n_episodes) in text and rule_of_three(n_groups) in text
    # the two object-present episodes of a group share their viewpoints but not the exact layout
    # (decision 002: the second one adds small occluder jitter)
    for ns in ("core", "holdout", "nav-b2"):
        groups: dict[int, list[dict]] = {}
        for e in load(f"data/episodes/gazebo-{ns}.json")["episodes"]:
            if e["ground_truth"]["object_present"]:
                groups.setdefault(e["spec"]["scene_group"], []).append(e["spec"])
        for a, b in groups.values():
            assert a["candidate_viewpoints"] == b["candidate_viewpoints"], ns
            assert a["initial_viewpoint"] == b["initial_viewpoint"], ns
    assert "share viewpoints and the base obstacle layout" in README_EN
    assert "共用視角與遮擋物基礎佈局" in README
    # the note under Key results points to the method and to the false-absent bounds only
    note = "the rule-of-three bound (about 3/n) and the false-absent bounds are given there"
    assert note in README_EN and "上界的算法（約 3/n）與 false absent 的上界列在那裡" in README
    # the zeros are Rule-NBV's (and every method's from decision-v2 on); under decision-v1 the
    # Random baseline made a few false-absent calls
    s, hv1 = t["summary"], h["v1"]["summary"]
    assert all(s[f"rule@{b}"]["false_absent_rate"] == 0 for b in range(1, 9))
    assert all(hv1[f"rule@{b}"]["false_absent_rate"] == 0 for b in range(1, 9))
    for text in (README, README_EN):
        assert f"{s['random@2']['false_absent_rate']:.4f}" in text
        assert f"{hv1['random@2']['false_absent_rate']:.5f}" in text


def test_sealing_claims_match_the_manifest():
    """Only the v1 / v2 frozen configs are pinned, and only the v1 / v2 runners refuse a re-run."""
    lines = (ROOT / "SEALED.sha256").read_text().splitlines()
    pinned = [ln.split("  ", 1)[1] for ln in lines if ln.strip()]
    code = sorted(p for p in pinned if p.startswith("activeperception/"))
    assert code == ["activeperception/frozen.py", "activeperception/frozen_v2.py"]
    for v in (3, 4, 5):
        src = (ROOT / f"activeperception/v{v}/formal.py").read_text()
        assert "guard_formal_run" not in src and "report.json exists" in src
    # the other formal runners only refuse to overwrite their own output ...
    for rel in ("r0a.py", "r0b.py", "detv2/formal.py"):
        src = (ROOT / "activeperception" / rel).read_text()
        assert "guard_formal_run" not in src and " exists: the formal " in src, rel
    # ... and the Nav2 batches only skip jobs that already have a result
    for rel, done in (("docker/nav_b0.sh", "episode.json"), ("docker/nav_b1.sh", "run.json")):
        src = (ROOT / rel).read_text()
        assert "guard_formal_run" not in src and f"with {done} is skipped" in src, rel
    assert "`frozen_v3.py`–`frozen_v5.py` are not pinned" in README_EN
    assert "`frozen_v3.py`–`frozen_v5.py` 沒有釘住" in README
    assert "frozen episode set and frozen config;" not in README_EN
    runners = "(R0a, R0b, detector-v2, v3–v5) only refuse to overwrite their own existing output"
    assert f"The other formal runners {runners}" in README_EN
    assert "其他正式 runner（R0a、R0b、detector-v2、v3–v5）只拒絕覆寫自己已有的輸出" in README
    assert "the Nav2 batches (`nav-b0*`, `nav-b2`) only skip jobs" in README_EN
    assert "Nav2 批次（`nav-b0*`、`nav-b2`）只跳過輸出目錄裡已有結果的工作" in README


def test_see_through_guarantee_is_scoped():
    """The guarantee that the object's own place is never seen through needs an exact pose and
    exact depth: pose error alone (B0, R0b) and depth error alone (R0b) broke it in the results."""
    b0 = load("results/nav-b0/b0_report.json")["decisions"]
    assert b0["all_views_geometric_risk_episodes"] > 0  # AMCL poses alone
    by = {tuple(r["condition"].values()): r for r in load("results/r0b/report.json")["results"]}
    for d, q in (("D0", "L1"), ("D0", "L2"), ("D1", "P0"), ("D2", "P0")):  # pose only, depth only
        assert by[(d, q, "a")]["all_views_geometric_risk"], (d, q)
    # pipeline (b): pose refinement + see-through margin (decision 016)
    assert not any(r["all_views_geometric_risk"] for (_, _, p), r in by.items() if p == "b")
    assert "With an exact camera pose and exact depth, the place where the object" in README_EN
    assert "在相機位姿與 depth 都精確時，物件真正站的位置不可能被看穿" in README


def test_mechanism_notes_match_the_frozen_rules():
    """The notes next to the Single floor and the ECE drop restate the frozen decision rules."""
    from types import SimpleNamespace

    from activeperception.decision import DecisionRule
    from activeperception.frozen import DECISION_V1
    from activeperception.frozen_v2 import DECISION_V2
    from activeperception.types import Decision

    def view(azimuth: float) -> SimpleNamespace:  # an unobstructed view without a detection
        return SimpleNamespace(
            viewpoint=SimpleNamespace(azimuth=azimuth),
            zone_visible_fraction=1.0,
            max_confidence=0.0,
        )

    sectors = DECISION_V1.n_sectors
    need = round(DECISION_V1.min_coverage * sectors)
    assert (sectors, need) == (8, 2)
    assert f"≥ {need} of {sectors} sectors" in README_EN
    assert f"要 ≥ {need} 個有效扇區（共 {sectors} 個）" in README
    rule = DecisionRule(DECISION_V1)
    # one view lies in one sector, so decision-v1 never answers absent from a single view
    for k in range(24):
        assert rule.decide(None, [view(k * math.pi / 12)]).decision != Decision.ABSENT
    # a correct absent from 2 of 8 sectors: confidence = coverage x (1 - c_max) = 0.25 at most
    two = rule.decide(None, [view(0.1), view(0.1 + 2 * math.pi / sectors)])
    assert two.decision == Decision.ABSENT and two.confidence == DECISION_V1.min_coverage
    assert f"gets at most {two.confidence}" in README_EN
    assert f"正確的 absent 最多也只有 {two.confidence}" in README
    # v2 answers absent only when every candidate location is seen through
    assert DECISION_V2.tau_clear == 1.0
    assert "that fraction is always 1 when v2 answers `absent`" in README_EN
    assert "v2 判 absent 時看穿比例一定是 1" in README
