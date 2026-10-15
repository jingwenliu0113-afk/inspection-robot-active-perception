"""v5 formal evaluation (decision 034): frozen v5 against frozen v4 on new data, run once.

    uv run python -m activeperception.v5.formal --out results/v5 --raw runs/v5-formal

Inputs per namespace (``v5``, ``v5-dx``): ``data/episodes/gazebo-<ns>.json``, ``renders/<ns>``
and ``runs/<ns>/detector-v1.jsonl``. Pipelines: frozen v4 (reference), frozen v5, and v5 without
bracketing (report only). Writes ``report.json`` and ``tables.md``; per-view diagnostics go to
``--raw``. Refuses to run twice. Starts only when no other project holds the Mac heavy lock; if
one takes it during the run, the next job waits until it is released (the run stays complete).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..v3 import formal as v3f
from ..v3.eval import run
from ..v4 import formal as v4f
from ..v4 import frozen_v4
from . import frozen_v5, maclock

FORMAL_NAMESPACES = ("v5", "v5-dx")
# (namespace, depth, true pose error, pose error the localiser reports or None = honest)
CONDITIONS = (
    ("v5", "D0", "P0", None),
    ("v5", "D1", "L1", None),
    ("v5", "D2", "L2", None),
    ("v5", "D3", "L1", None),
    ("v5", "D3", "P0", None),
    ("v5", "D1", "L2", "L1"),
    ("v5-dx", "D1", "L1", None),
    ("v5-dx", "D3", "L1", None),
)
PIPELINES = {  # name -> (geometry config, zone gating, tie-break)
    "v4": (frozen_v4.CONFIG_NAME, True, frozen_v4.TIE_BREAK),
    "v5": (frozen_v5.GEOMETRY, True, frozen_v5.TIE_BREAK),
    "v5-free": (frozen_v5.FREE, True, frozen_v5.TIE_BREAK),
}
BUDGETS = (2, 3, 5)


def jobs() -> list[tuple]:
    return [
        (ns, d, p, cfg, gated, tie, prior)
        for ns, d, p, prior in CONDITIONS
        for cfg, gated, tie in PIPELINES.values()
    ]


def pipeline_of(cfg) -> str:
    name = cfg if isinstance(cfg, str) else cfg.name
    return {frozen_v4.CONFIG_NAME: "v4", frozen_v5.CONFIG_NAME: "v5", "v5-free": "v5-free"}[name]


def key(ns: str, d: str, p: str, prior: str | None, pipeline: str) -> str:
    return v4f.key(ns, d, p, prior, pipeline)


def run_when_free(job: tuple) -> dict:
    while maclock.holder() is not None:  # another project's heavy work: wait, do not compete
        time.sleep(60)
    return run(job)


def _diff(res: dict, groups: dict, base: str, a: str, b: str, budget: int) -> dict:
    from ..frozen import BOOT_SEED, N_BOOT
    from ..nav.b1_analysis import cluster_bootstrap

    ea, eb = res[f"{base}:{a}"]["rule_per_episode"], res[f"{base}:{b}"]["rule_per_episode"]
    eids = sorted(ea)
    g = np.array([groups[e] for e in eids])
    d = np.array([v3f.correct(ea[e], budget) - v3f.correct(eb[e], budget) for e in eids], float)
    out = cluster_bootstrap(d, g, N_BOOT, BOOT_SEED)
    out[f"{a}_only_correct"] = int((d > 0).sum())
    out[f"{b}_only_correct"] = int((d < 0).sum())
    return out


def paired(res: dict[str, dict], groups: dict[str, int]) -> dict:
    """Rule, v5 - v4 and v5-free - v4 per condition and budget (same episodes and draws)."""
    out = {}
    for k in res:
        if not k.endswith(":v4"):
            continue
        base = k[: -len(":v4")]
        out[base] = {
            f"{a}@{b}": _diff(res, groups, base, a, "v4", b)
            for a in ("v5", "v5-free")
            for b in BUDGETS
        }
    return out


def _absent(c: dict) -> float:
    return c["summary"]["rule@5"]["accuracy_by_state"]["absent"]


def verdicts(res: dict[str, dict], diff: dict) -> dict:
    """The pre-registered criteria (decision 034 §4)."""
    v5 = {k: c for k, c in res.items() if k.endswith(":v5")}
    out = {
        "X1": {
            "pass": len(v5) == len(CONDITIONS) and all(v3f.safe(c) for c in v5.values()),
            "unsafe": sorted(k for k, c in v5.items() if not v3f.safe(c)),
            "rule": "v5 in all 8 conditions: FA, FP, GR, all-views GR, occupied clearance = 0",
        }
    }
    x2 = {}
    for d, p in frozen_v5.X2_CONDITIONS:
        r = diff[f"v5:{d}x{p}"][f"v5@{frozen_v5.X2_BUDGET}"]
        x2[f"{d}x{p}"] = r
    out["X2"] = {
        "pass": all(r["ci95"][0] > 0 for r in x2.values()),
        "rule_b3_v5_minus_v4": x2,
        "rule": "v5 D2xL2 and D3xL1: Rule budget-3 accuracy v5 - v4, cluster-bootstrap 95% CI "
        "lower bound > 0",
    }
    a, b = res[key("v5", "D0", "P0", None, "v4")], res[key("v5", "D0", "P0", None, "v5")]
    same = a["summary"] == b["summary"] and a["rule_per_episode"] == b["rule_per_episode"]
    out["X3"] = {"pass": bool(same), "rule": "v5 D0xP0: v5 outcomes identical to v4"}
    worse = [
        f"{base}@{bud}"
        for base, per in diff.items()
        for bud in BUDGETS
        if per[f"v5@{bud}"]["ci95"][1] < 0
    ]
    out["X4"] = {
        "pass": not worse,
        "significantly_worse": worse,
        "rule": "no condition x budget (2 / 3 / 5) with a v5 - v4 CI upper bound < 0",
    }
    out["R1"] = {
        "absent_accuracy_rule_b5": {
            k.rsplit(":", 1)[0]: {"v4": _absent(res[k[: -len(":v5")] + ":v4"]), "v5": _absent(c)}
            for k, c in v5.items()
        },
        "rule": "report only",
    }
    free = {k: c for k, c in res.items() if k.endswith(":v5-free")}
    out["R2"] = {
        "safe": {k.rsplit(":", 1)[0]: v3f.safe(c) for k, c in free.items()},
        "absent_accuracy_rule_b5": {k.rsplit(":", 1)[0]: _absent(c) for k, c in free.items()},
        "rule": "report only: v5 without bracketing",
    }
    return dict(sorted(out.items()))


def markdown(res: dict[str, dict], ver: dict, diff: dict) -> str:
    out = ["# v5 正式測試：模擬誤差，不是實機", "", "| 判準 | 結果 |", "|---|---|"]
    for k in ("X1", "X2", "X3", "X4"):
        v = ver[k]
        extra = ""
        if k == "X2":
            extra = (
                "（"
                + "、".join(
                    f"{c} {r['mean']:+.3f} [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]"
                    for c, r in v["rule_b3_v5_minus_v4"].items()
                )
                + "）"
            )
        if k == "X1" and v["unsafe"]:
            extra = "（" + "、".join(v["unsafe"]) + "）"
        if k == "X4" and v["significantly_worse"]:
            extra = "（" + "、".join(v["significantly_worse"]) + "）"
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
    for a in ("v5", "v5-free"):
        out += [
            "",
            f"Rule：{a} − v4 準確率（成對，scene group cluster bootstrap 95% CI；"
            f"只有 {a} 對 / 只有 v4 對）",
            "",
        ]
        out += ["| 資料 / 條件 | budget 2 | budget 3 | budget 5 |", "|---|---|---|---|"]
        for base, per in diff.items():
            cells = []
            for b in BUDGETS:
                r = per[f"{a}@{b}"]
                cells.append(
                    f"{r['mean']:+.3f} [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}] "
                    f"({r[f'{a}_only_correct']} / {r['v4_only_correct']})"
                )
            out.append(f"| {base} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def check_inputs() -> dict[str, int]:
    """Formal sets must exist, be v5-eval and carry detector-v1 detections. Returns groups."""
    from ..serialize import load_episode_set
    from ..types import Split

    groups = {}
    for ns in FORMAL_NAMESPACES:
        specs, _, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
        if any(s.split != Split.V5_EVAL for s in specs):
            raise SystemExit(f"{ns}: not a v5-eval set")
        if not Path(f"runs/{ns}/detector-v1.jsonl").exists():
            raise SystemExit(f"{ns}: run detector-v1 first")
        groups |= {s.episode_id: s.scene_group for s in specs}
    return groups


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v5.formal")
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    out, raw = Path(args.out), Path(args.raw)
    if (out / "report.json").exists():
        sys.exit(f"{out}/report.json exists: the formal v5 run is done once")
    groups = check_inputs()
    maclock.require_free()
    raw.mkdir(parents=True, exist_ok=True)
    res = {}
    with ProcessPoolExecutor(min(args.workers, len(jobs()))) as ex:
        for job, r in zip(jobs(), ex.map(run_when_free, jobs()), strict=True):
            ns, d, p, cfg, *_rest, prior = job
            k = key(ns, d, p, prior, pipeline_of(cfg))
            (raw / f"{k.replace(':', '_')}.json").write_text(json.dumps(r) + "\n")
            res[k] = v4f.compact(r)
            print(k, "safe" if v3f.safe(res[k]) else "UNSAFE", flush=True)
    diff = paired(res, groups)
    ver = verdicts(res, diff)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "frozen_v4": frozen_v4.describe(),
        "frozen_v5": frozen_v5.describe(),
        "verdicts": ver,
        "paired_minus_v4": diff,
        "results": res,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    (out / "tables.md").write_text(markdown(res, ver, diff))
    print(json.dumps({k: v.get("pass") for k, v in ver.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
