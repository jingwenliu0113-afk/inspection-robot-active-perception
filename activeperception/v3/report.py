"""Tables for v3 development runs (decision 024): one row per (condition, config, gate, tie-break).

uv run python -m activeperception.v3.report runs/v3-dev/geometry [more dirs]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def row(r: dict) -> dict:
    s, j = r["summary"], r["job"]
    views = r["views"]
    err = np.array([v["err_xy"] for v in views])
    ok = [v["refine_ok"] for v in views]
    return {
        "ns": views[0]["episode"].rsplit("-g", 1)[0],  # episode ids are <ns>-g<group>-v<variant>
        "condition": f"{j['depth']}x{j['pose']}" + (f" 回報{j['prior']}" if j.get("prior") else ""),
        "config": j["config"],
        "gated": j["gated"],
        "tie_break": j["tie_break"],
        "false_absent": sum(v["false_absent"] for v in s.values()),
        "false_present": sum(v["false_present"] for v in s.values()),
        "geometric_risk": sum(v["geometric_risk"] for v in s.values()),
        "all_views_risk": len(r["all_views_geometric_risk"]),
        "occupied": r["occupied_false_clearance"]["views"],
        "present_views": r["occupied_false_clearance"]["present_views"],
        "rule_b2": s["rule@2"]["accuracy"],
        "rule_b3": s["rule@3"]["accuracy"],
        "rule_b5": s["rule@5"]["accuracy"],
        "absent_b5": s["rule@5"]["accuracy_by_state"]["absent"],
        "random_b3": s["random@3"]["accuracy"],
        "oracle_b3": s["oracle@3"]["accuracy"],
        "err_p95_cm": float(np.quantile(err, 0.95) * 100),
        "err_max_cm": float(err.max() * 100),
        "refine_ok": float(np.mean(ok)),
    }


def by_state(r: dict, budget: int = 5) -> dict[str, dict[str, int]]:
    """Rule's decisions per GT state (the occlusion view: is "not seen" ever reported as absent?)"""
    out: dict[str, dict[str, int]] = {}
    for e in (r.get("rule_per_episode") or {}).values():
        d = out.setdefault(e["state"], {"present": 0, "absent": 0, "inconclusive": 0})
        d[e[f"b{budget}"]] += 1
    return out


def state_markdown(dirs: list[str], budget: int = 5) -> str:
    out = [
        f"| 條件 | 設定 | zone 過濾 | visible（P / A / I） | unobservable（P / A / I） "
        f"| absent（P / A / I） |  ← budget {budget}",
        "|---|---|---|---|---|---|",
    ]
    for d in dirs:
        for f in sorted(Path(d).glob("*.json")):
            r = json.loads(f.read_text())
            s = by_state(r, budget)
            if not s:
                continue
            j = r["job"]
            cells = [
                " / ".join(
                    str(s.get(k, {}).get(x, 0)) for x in ("present", "absent", "inconclusive")
                )
                for k in ("visible", "unobservable", "absent")
            ]
            out.append(
                f"| {j['depth']}x{j['pose']} | {j['config']} | {'on' if j['gated'] else '—'} | "
                + " | ".join(cells)
                + " |"
            )
    return "\n".join(out) + "\n"


def load(dirs: list[str]) -> list[dict]:
    rows = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.json")):
            rows.append(row(json.loads(f.read_text())))
    return rows


def markdown(rows: list[dict]) -> str:
    head = (
        "| 條件 | 設定 | zone 過濾 | 平手處理 | FA | FP | GR | 全視角 | 佔用看穿 "
        "| Rule b2 / b3 / b5 | absent@5 | Oracle b3 | 位姿誤差 p95 / max | 精修成功 |"
    )
    out = [head, "|" + "---|" * 14]
    for r in rows:
        safe = r["false_absent"] == 0 and r["geometric_risk"] == 0 and r["all_views_risk"] == 0
        occ = f"{r['occupied']}/{r['present_views']}"
        out.append(
            f"| {r['condition']} | {r['config']} | {'on' if r['gated'] else '—'} | "
            f"{'on' if r['tie_break'] else '—'} | {r['false_absent']} | {r['false_present']} | "
            f"{r['geometric_risk']} | {r['all_views_risk']}{'' if safe else ' ✗'} | {occ} | "
            f"{r['rule_b2']:.3f} / {r['rule_b3']:.3f} / {r['rule_b5']:.3f} "
            f"| {r['absent_b5']:.3f} | "
            f"{r['oracle_b3']:.3f} | {r['err_p95_cm']:.1f} / {r['err_max_cm']:.1f} cm "
            f"| {r['refine_ok']:.2f} |"
        )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--states":  # --states DIR... : decisions per GT state
        print(state_markdown(args[1:]))
        raise SystemExit(0)
    if args and args[0] == "--json":  # --json OUT DIR... : write the rows too
        out, dirs = Path(args[1]), args[2:]
        rows = load(dirs)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"note": "development data (decision 024)", "rows": rows}, indent=1) + "\n"
        )
    else:
        rows = load(args)
    print(markdown(rows))
