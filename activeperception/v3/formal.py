"""v3 formal evaluation (decision 025): the frozen v3 against v2 on new data, run once.

    uv run python -m activeperception.v3.formal --out results/v3 --raw runs/v3-formal

Inputs per namespace (``v3``, ``v3-dx``): ``data/episodes/gazebo-<ns>.json``, ``renders/<ns>``
and ``runs/<ns>/detector-v1.jsonl``. Writes ``report.json`` (per job: summary, safety counts,
Rule's decision per episode, pose / gate statistics; verdicts V1-V6) and ``tables.md``; the
per-view diagnostics go to ``--raw`` (not committed, reproducible). Refuses to run twice.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import frozen_v3
from .eval import run

FORMAL_NAMESPACES = ("v3", "v3-dx")
# (namespace, depth, true pose error, pose error the localiser reports or None = honest)
CONDITIONS = (
    ("v3", "D0", "P0", None),
    ("v3", "D1", "L1", None),  # V1 / V2
    ("v3", "D2", "L2", None),  # V4
    ("v3", "D1", "L2", "L1"),  # V5: M, localiser 2x over-confident
    ("v3-dx", "D0", "P0", None),  # V3
    ("v3-dx", "D1", "L1", None),  # V3
)
PIPELINES = {  # name -> (geometry config, zone gating, tie-break)
    "v2": ("v2", False, False),
    "v3": (frozen_v3.CONFIG_NAME, True, frozen_v3.TIE_BREAK),
}
ABSENT_MIN = 0.90  # V2


def jobs() -> list[tuple]:
    return [
        (ns, d, p, cfg, gated, tie, prior)
        for ns, d, p, prior in CONDITIONS
        for cfg, gated, tie in PIPELINES.values()
    ]


def key(ns: str, d: str, p: str, prior: str | None, pipeline: str) -> str:
    return f"{ns}:{d}x{p}" + (f"-reports{prior}" if prior else "") + f":{pipeline}"


def compact(r: dict) -> dict:
    """What the report keeps of one run (the per-view list is summarised)."""
    v = r["views"]
    err = np.array([x["err_xy"] for x in v])
    flags = [f for x in v for f in (x["gate"] or [])]
    s = r["summary"]
    return {
        "job": r["job"],
        "summary": s,
        "false_absent": sum(x["false_absent"] for x in s.values()),
        "false_present": sum(x["false_present"] for x in s.values()),
        "geometric_risk": sum(x["geometric_risk"] for x in s.values()),
        "all_views_geometric_risk": r["all_views_geometric_risk"],
        "occupied_false_clearance": r["occupied_false_clearance"],
        "rule_per_episode": r["rule_per_episode"],
        "pose_error_m": {
            "p50": float(np.quantile(err, 0.5)),
            "p95": float(np.quantile(err, 0.95)),
            "max": float(err.max()),
        },
        "refine_ok": float(np.mean([x["refine_ok"] for x in v])),
        "gate_flags": {k: flags.count(k) for k in ("in", "out", "unknown")},
        "n_views": len(v),
    }


def safe(c: dict) -> bool:
    return (
        c["false_absent"] == 0
        and c["false_present"] == 0
        and c["geometric_risk"] == 0
        and not c["all_views_geometric_risk"]
        and c["occupied_false_clearance"]["views"] == 0
    )


def verdicts(res: dict[str, dict]) -> dict:
    v3 = {k: c for k, c in res.items() if k.endswith(":v3")}
    typical = v3[key("v3", "D1", "L1", None, "v3")]
    absent = typical["summary"]["rule@5"]["accuracy_by_state"]["absent"]
    dx = [v3[key("v3-dx", d, p, None, "v3")] for d, p in (("D0", "P0"), ("D1", "L1"))]
    return {
        "V1": {"pass": safe(typical), "rule": "v3, v3 D1xL1: FA, FP, GR, all-views, occupied = 0"},
        "V2": {
            "pass": absent >= ABSENT_MIN,
            "absent_accuracy_rule_b5": absent,
            "rule": f"v3, v3 D1xL1: Rule budget-5 absent accuracy >= {ABSENT_MIN}",
        },
        "V3": {"pass": all(safe(c) for c in dx), "rule": "v3, v3-dx D0xP0 and D1xL1: as V1"},
        "V4": {"pass": safe(v3[key("v3", "D2", "L2", None, "v3")]), "rule": "v3 D2xL2 as V1"},
        "V5": {
            "pass": safe(v3[key("v3", "D1", "L2", "L1", "v3")]),
            "rule": "v3 D1xL2, localiser reports L1: as V1",
        },
        "V6": "report only (tables.md)",
    }


def correct(e: dict, b: int) -> bool:
    return e[f"b{b}"] == ("absent" if e["state"] == "absent" else "present")


def paired(res: dict[str, dict], groups: dict[str, int]) -> dict:
    """V6: Rule, v3 - v2 accuracy per condition (same episodes, same error draws), with a
    scene-group cluster bootstrap CI."""
    from ..frozen import BOOT_SEED, N_BOOT
    from ..nav.b1_analysis import cluster_bootstrap

    out = {}
    for k3, c3 in res.items():
        if not k3.endswith(":v3"):
            continue
        k2 = k3[: -len(":v3")] + ":v2"
        e3, e2 = c3["rule_per_episode"], res[k2]["rule_per_episode"]
        eids = sorted(e3)
        g = np.array([groups[e] for e in eids])
        out[k3[: -len(":v3")]] = {
            f"rule@{b}": {
                **cluster_bootstrap(
                    np.array([correct(e3[e], b) - correct(e2[e], b) for e in eids], float),
                    g,
                    N_BOOT,
                    BOOT_SEED,
                ),
                "v3_only_correct": sum(correct(e3[e], b) and not correct(e2[e], b) for e in eids),
                "v2_only_correct": sum(correct(e2[e], b) and not correct(e3[e], b) for e in eids),
            }
            for b in (2, 3, 5)
        }
    return out


def markdown(res: dict[str, dict], ver: dict, diff: dict) -> str:
    out = ["# v3 正式測試（decision 025 / 026）：模擬誤差，不是實機", ""]
    out += ["| 判準 | 結果 |", "|---|---|"]
    for k in ("V1", "V2", "V3", "V4", "V5"):
        extra = f"（absent {ver[k]['absent_accuracy_rule_b5']:.3f}）" if k == "V2" else ""
        out.append(f"| {k} | {'通過' if ver[k]['pass'] else '**未通過**'}{extra} |")
    head = (
        "| 資料 / 條件 | 管線 | FA | FP | GR | 全視角 | 佔用看穿 | Rule b2 / b3 / b5 | absent@5 "
        "| Random b3 | Oracle b3 | 位姿誤差 p95 | 精修成功 |"
    )
    out += ["", head, "|" + "---|" * 13]
    for k, c in res.items():
        s = c["summary"]
        occ = c["occupied_false_clearance"]
        out.append(
            f"| {k.rsplit(':', 1)[0]} | {c['job']['config']}"
            f"{' + zone' if c['job']['gated'] else ''} | {c['false_absent']} "
            f"| {c['false_present']} | {c['geometric_risk']} "
            f"| {len(c['all_views_geometric_risk'])} | {occ['views']}/{occ['present_views']} "
            f"| {s['rule@2']['accuracy']:.3f} / {s['rule@3']['accuracy']:.3f} / "
            f"{s['rule@5']['accuracy']:.3f} | {s['rule@5']['accuracy_by_state']['absent']:.3f} "
            f"| {s['random@3']['accuracy']:.3f} | {s['oracle@3']['accuracy']:.3f} "
            f"| {c['pose_error_m']['p95'] * 100:.1f} cm | {c['refine_ok']:.2f} |"
        )
    out += ["", "Rule：v3 − v2 準確率（成對，scene group cluster bootstrap 95% CI）", ""]
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
    ap = argparse.ArgumentParser(prog="activeperception.v3.formal")
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args(argv)
    out, raw = Path(args.out), Path(args.raw)
    if (out / "report.json").exists():
        sys.exit(f"{out}/report.json exists: the formal v3 run is done once (decision 025)")
    raw.mkdir(parents=True, exist_ok=True)
    res = {}
    with ProcessPoolExecutor(min(args.workers, len(jobs()))) as ex:
        for job, r in zip(jobs(), ex.map(run, jobs()), strict=True):
            ns, d, p, cfg, *_rest, prior = job
            pipeline = "v3" if cfg == frozen_v3.CONFIG_NAME else "v2"
            k = key(ns, d, p, prior, pipeline)
            (raw / f"{k.replace(':', '_')}.json").write_text(json.dumps(r) + "\n")
            res[k] = compact(r)
            print(k, "safe" if safe(res[k]) else "UNSAFE", flush=True)
    from ..serialize import load_episode_set

    groups = {
        s.episode_id: s.scene_group
        for ns in FORMAL_NAMESPACES
        for s in load_episode_set(f"data/episodes/gazebo-{ns}.json")[0]
    }
    ver, diff = verdicts(res), paired(res, groups)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "decision": "025",
        "frozen": frozen_v3.describe(),
        "verdicts": ver,
        "v3_minus_v2": diff,
        "results": res,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    (out / "tables.md").write_text(markdown(res, ver, diff))
    print(json.dumps(ver, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
