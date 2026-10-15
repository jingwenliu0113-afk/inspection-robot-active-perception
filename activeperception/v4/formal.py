"""v4 + D3 formal evaluation: frozen v4 against frozen v3 on new data, run once.

    uv run python -m activeperception.v4.formal --out results/v4 --raw runs/v4-formal

Inputs per namespace (``v4``, ``v4-dx``): ``data/episodes/gazebo-<ns>.json``, ``renders/<ns>``
and ``runs/<ns>/detector-v1.jsonl``. The same data answers two questions: is frozen v3 safe under
D3 (the D3 formal check, decision 028 §5), and does v4 fix the V4 failure. Writes ``report.json``
and ``tables.md``; per-view diagnostics go to ``--raw``. Refuses to run twice.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..v3 import formal as v3f
from ..v3 import frozen_v3
from ..v3.eval import run
from . import frozen_v4

FORMAL_NAMESPACES = ("v4", "v4-dx")
# (namespace, depth, true pose error, pose error the localiser reports or None = honest)
CONDITIONS = (
    ("v4", "D0", "P0", None),
    ("v4", "D1", "L1", None),
    ("v4", "D2", "L2", None),
    ("v4", "D3", "L1", None),
    ("v4", "D3", "P0", None),
    ("v4", "D1", "L2", "L1"),
    ("v4-dx", "D1", "L1", None),
    ("v4-dx", "D3", "L1", None),
)
PIPELINES = {  # name -> (geometry config, zone gating, tie-break)
    "v3": (frozen_v3.CONFIG_NAME, True, frozen_v3.TIE_BREAK),
    "v4": (frozen_v4.CONFIG_NAME, True, frozen_v4.TIE_BREAK),
}


def jobs() -> list[tuple]:
    return [
        (ns, d, p, cfg, gated, tie, prior)
        for ns, d, p, prior in CONDITIONS
        for cfg, gated, tie in PIPELINES.values()
    ]


def key(ns: str, d: str, p: str, prior: str | None, pipeline: str) -> str:
    return f"{ns}:{d}x{p}" + (f"-reports{prior}" if prior else "") + f":{pipeline}"


def compact(r: dict) -> dict:
    """v3's summary of a run plus the per-view margin exceedance (views whose pose was used
    with a true position error beyond the margin applied to them)."""
    c = v3f.compact(r)
    used = [x for x in r["views"] if not x["blind"] and x["margin_xy"] is not None]
    c["exceed"] = {
        "used": sum(x["err_xy"] > x["margin_xy"] for x in used),
        "refined_ok": sum(x["err_xy"] > x["margin_xy"] for x in used if x["refine_ok"]),
        "n_used": len(used),
        "n_refined_ok": sum(bool(x["refine_ok"]) for x in r["views"]),
    }
    c["blind_views"] = sum(bool(x["blind"]) for x in r["views"])
    c["gate_flags"]["maybe"] = sum(f == "maybe" for x in r["views"] for f in (x["gate"] or []))
    c["margin_xy_p50"] = float(np.median([x["margin_xy"] for x in used])) if used else None
    return c


def _absent(c: dict) -> float:
    return c["summary"]["rule@5"]["accuracy_by_state"]["absent"]


def verdicts(res: dict[str, dict]) -> dict:
    """The pre-registered criteria (see the freeze decision)."""
    k = lambda ns, d, p, pipe, prior=None: res[key(ns, d, p, prior, pipe)]  # noqa: E731
    w = {
        "W1": ("v4 D1xL1: as V1", [k("v4", "D1", "L1", "v4")]),
        "W3": ("v4 D2xL2: as V1 (the V4 failure)", [k("v4", "D2", "L2", "v4")]),
        "W4": ("v4 D3xL1: as V1", [k("v4", "D3", "L1", "v4")]),
        "W6": (
            "v4-dx D1xL1 and D3xL1, v4 D3xP0, v4 D1xL2 reporting L1: as V1",
            [
                k("v4-dx", "D1", "L1", "v4"),
                k("v4-dx", "D3", "L1", "v4"),
                k("v4", "D3", "P0", "v4"),
                k("v4", "D1", "L2", "v4", "L1"),
            ],
        ),
        "D1": (
            "frozen v3 under D3 (D3xL1, D3xP0, v4-dx D3xL1): as V1",
            [k("v4", "D3", "L1", "v3"), k("v4", "D3", "P0", "v3"), k("v4-dx", "D3", "L1", "v3")],
        ),
    }
    out = {
        name: {"pass": all(v3f.safe(c) for c in cs), "rule": rule} for name, (rule, cs) in w.items()
    }
    a1, a3 = _absent(k("v4", "D1", "L1", "v4")), _absent(k("v4", "D3", "L1", "v4"))
    out["W2"] = {
        "pass": a1 >= frozen_v4.ABSENT_MIN,
        "absent_accuracy_rule_b5": a1,
        "rule": f"v4 D1xL1: Rule budget-5 absent accuracy >= {frozen_v4.ABSENT_MIN}",
    }
    ratios = {}
    for d, p in (("D2", "L2"), ("D3", "L1")):
        e4 = k("v4", d, p, "v4")["exceed"]["refined_ok"]
        e3 = k("v4", d, p, "v3")["exceed"]["refined_ok"]
        ratios[f"{d}x{p}"] = {"v4": e4, "v3": e3, "ratio": e4 / e3 if e3 else None}
    out["W5"] = {
        "pass": all(
            r["v4"] <= frozen_v4.EXCEED_MAX_RATIO * r["v3"] if r["v3"] else r["v4"] == 0
            for r in ratios.values()
        ),
        "exceed_refined_ok": ratios,
        "rule": f"v4 D2xL2 and D3xL1: margin exceedance of trusted fits <= "
        f"{frozen_v4.EXCEED_MAX_RATIO} x frozen v3's on the same data",
    }
    out["R1"] = {
        "absent_accuracy_rule_b5": {"v4": a3, "v3": _absent(k("v4", "D3", "L1", "v3"))},
        "rule": "report only: absent@5 under D3xL1, v4 and frozen v3",
    }
    return dict(sorted(out.items()))


def paired(res: dict[str, dict], groups: dict[str, int]) -> dict:
    """Rule, v4 - v3 accuracy per condition (same episodes, same error draws), scene-group
    cluster bootstrap."""
    from ..frozen import BOOT_SEED, N_BOOT
    from ..nav.b1_analysis import cluster_bootstrap

    out = {}
    for k4, c4 in res.items():
        if not k4.endswith(":v4"):
            continue
        base = k4[: -len(":v4")]
        e4, e3 = c4["rule_per_episode"], res[base + ":v3"]["rule_per_episode"]
        eids = sorted(e4)
        g = np.array([groups[e] for e in eids])
        out[base] = {
            f"rule@{b}": {
                **cluster_bootstrap(
                    np.array([v3f.correct(e4[e], b) - v3f.correct(e3[e], b) for e in eids], float),
                    g,
                    N_BOOT,
                    BOOT_SEED,
                ),
                "v4_only_correct": sum(
                    v3f.correct(e4[e], b) and not v3f.correct(e3[e], b) for e in eids
                ),
                "v3_only_correct": sum(
                    v3f.correct(e3[e], b) and not v3f.correct(e4[e], b) for e in eids
                ),
            }
            for b in (2, 3, 5)
        }
    return out


def markdown(res: dict[str, dict], ver: dict, diff: dict) -> str:
    out = ["# v4 + D3 正式測試：模擬誤差，不是實機", "", "| 判準 | 結果 |", "|---|---|"]
    for k, v in ver.items():
        if "pass" not in v:
            a = v["absent_accuracy_rule_b5"]
            out.append(f"| {k} | 只報告：absent@5 v4 {a['v4']:.3f}、v3 {a['v3']:.3f} |")
            continue
        extra = ""
        if "absent_accuracy_rule_b5" in v:
            extra = f"（absent {v['absent_accuracy_rule_b5']:.3f}）"
        if "exceed_refined_ok" in v:
            extra = (
                "（"
                + "、".join(f"{c} {r['v4']} / {r['v3']}" for c, r in v["exceed_refined_ok"].items())
                + "）"
            )
        out.append(f"| {k} | {'通過' if v['pass'] else '**未通過**'}{extra} |")
    head = (
        "| 資料 / 條件 | 管線 | FA | FP | GR | 全視角 | 佔用看穿 | 超出餘裕（精修成功） "
        "| 不提供看穿 | Rule b2 / b3 / b5 | absent@5 | 餘裕中位 | 位姿誤差 p95 |"
    )
    out += ["", head, "|" + "---|" * 13]
    for k, c in res.items():
        s, occ, ex = c["summary"], c["occupied_false_clearance"], c["exceed"]
        med = "—" if c["margin_xy_p50"] is None else f"{c['margin_xy_p50'] * 100:.1f} cm"
        out.append(
            f"| {k.rsplit(':', 1)[0]} | {k.rsplit(':', 1)[1]} | {c['false_absent']} "
            f"| {c['false_present']} | {c['geometric_risk']} "
            f"| {len(c['all_views_geometric_risk'])} | {occ['views']}/{occ['present_views']} "
            f"| {ex['used']} ({ex['refined_ok']}) | {c['blind_views']} "
            f"| {s['rule@2']['accuracy']:.3f} / {s['rule@3']['accuracy']:.3f} / "
            f"{s['rule@5']['accuracy']:.3f} | {s['rule@5']['accuracy_by_state']['absent']:.3f} "
            f"| {med} | {c['pose_error_m']['p95'] * 100:.1f} cm |"
        )
    out += ["", "Rule：v4 − v3 準確率（成對，scene group cluster bootstrap 95% CI）", ""]
    out += ["| 資料 / 條件 | budget 2 | budget 3 | budget 5 |", "|---|---|---|---|"]
    for k, d in diff.items():
        cells = [
            f"{d[f'rule@{b}']['mean']:+.3f} [{d[f'rule@{b}']['ci95'][0]:+.3f}, "
            f"{d[f'rule@{b}']['ci95'][1]:+.3f}]"
            for b in (2, 3, 5)
        ]
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v4.formal")
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args(argv)
    out, raw = Path(args.out), Path(args.raw)
    if (out / "report.json").exists():
        sys.exit(f"{out}/report.json exists: the formal v4 / D3 run is done once")
    raw.mkdir(parents=True, exist_ok=True)
    res = {}
    with ProcessPoolExecutor(min(args.workers, len(jobs()))) as ex:
        for job, r in zip(jobs(), ex.map(run, jobs()), strict=True):
            ns, d, p, cfg, *_rest, prior = job
            pipeline = "v4" if cfg == frozen_v4.CONFIG_NAME else "v3"
            k = key(ns, d, p, prior, pipeline)
            (raw / f"{k.replace(':', '_')}.json").write_text(json.dumps(r) + "\n")
            res[k] = compact(r)
            print(k, "safe" if v3f.safe(res[k]) else "UNSAFE", flush=True)
    from ..serialize import load_episode_set

    groups = {
        s.episode_id: s.scene_group
        for ns in FORMAL_NAMESPACES
        for s in load_episode_set(f"data/episodes/gazebo-{ns}.json")[0]
    }
    ver, diff = verdicts(res), paired(res, groups)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "frozen_v3": frozen_v3.describe(),
        "frozen_v4": frozen_v4.describe(),
        "verdicts": ver,
        "v4_minus_v3": diff,
        "results": res,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    (out / "tables.md").write_text(markdown(res, ver, diff))
    print(json.dumps(ver, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
