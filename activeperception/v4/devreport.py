"""v4 development summary (decision 029): safety, the margin-exceedance proxy and cost per run.

    uv run python -m activeperception.v4.devreport runs/v4-dev/geometry runs/v3-dev/confirm ...

"exceed" counts views whose pose was used (not blind) with a true position error larger than the
margin the pipeline applied to it - the per-view safety assumption. An occupied location is only
cleared when such an error also points at the object, so "exceed" is a far more sensitive (and
development-only) signal than the occupied-clearance count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def summarize(r: dict) -> dict:
    s, occ, v = r["summary"], r["occupied_false_clearance"], r["views"]
    used = [x for x in v if not x.get("blind") and x.get("margin_xy") is not None]
    return {
        "FA": sum(x["false_absent"] for x in s.values()),
        "FP": sum(x["false_present"] for x in s.values()),
        "GR": sum(x["geometric_risk"] for x in s.values()),
        "allview": len(r["all_views_geometric_risk"]),
        "occ": occ["views"],
        "exceed": sum(x["err_xy"] > x["margin_xy"] for x in used),
        "exceed_ok": sum(x["err_xy"] > x["margin_xy"] for x in used if x["refine_ok"]),
        "views": len(v),
        "blind": sum(bool(x.get("blind")) for x in v),
        "ok": sum(bool(x["refine_ok"]) for x in v),
        "rule": [s[f"rule@{b}"]["accuracy"] for b in (2, 3, 5)],
        "absent5": s["rule@5"]["accuracy_by_state"]["absent"],
        "margin_med": sorted(x["margin_xy"] for x in used)[len(used) // 2] if used else None,
    }


def row(name: str, c: dict) -> str:
    rule = " / ".join(f"{a:.3f}" for a in c["rule"])
    med = "—" if c["margin_med"] is None else f"{c['margin_med'] * 100:.1f} cm"
    return (
        f"| {name} | {c['FA']} | {c['FP']} | {c['GR']} | {c['allview']} | {c['occ']} | "
        f"{c['exceed']} ({c['exceed_ok']}) | {c['ok']} / {c['blind']} | {med} | {rule} | "
        f"{c['absent5']:.3f} |"
    )


HEADER = (
    "| run | FA | FP | GR | 全視角 | 佔用看穿 | 超出餘裕（其中精修成功） "
    "| 精修成功 / 不提供看穿 | 餘裕中位 | Rule b2 / b3 / b5 | absent@5 |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|"
)


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    files = sorted(f for p in paths for f in (p.glob("*.json") if p.is_dir() else [p]))
    print(HEADER)
    for f in files:
        print(row(f"{f.parent.name}/{f.stem}", summarize(json.loads(f.read_text()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
