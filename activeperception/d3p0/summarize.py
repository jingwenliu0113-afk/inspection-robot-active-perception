"""Summary of the D3xP0 diagnosis (decision 037 §1.1-1.4) from ``diagnose`` outputs.

uv run python -m activeperception.d3p0.summarize runs/d3p0-diag --out results/d3p0-diag
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

COND_ORDER = ("D0xP0", "D3xP0", "D3xL1", "D1xL2_L1")


def load(path: Path) -> list[dict]:
    return [json.loads(x) for x in open(path)]


def cleared(views: list[dict], key: str, ids=None, blind_as=None) -> np.ndarray:
    """Locations seen through (col_min = 1) by the union of ``views`` (ids = subset of vp ids).
    ``blind_as``: for blind views use this key instead (e.g. the C1 counterfactual)."""
    out = None
    for v in views:
        if ids is not None and v["vp"] not in ids:
            continue
        k = blind_as if (blind_as and v["status"] == "blind" and blind_as in v) else key
        s = np.asarray(v[k]) >= 1.0 - 1e-9
        out = s if out is None else out | s
    return out if out is not None else np.zeros(0, bool)


def q(a, qs=(0.5, 0.95)) -> list[float] | None:
    a = np.asarray([x for x in a if x is not None], float)
    return [float(np.quantile(a, x)) for x in qs] if len(a) else None


def view_level(rows: list[dict]) -> dict:
    vs = [v for r in rows for v in r["views"]]
    by = {s: [v for v in vs if v["status"] == s] for s in ("ok", "blind", "fallback")}
    out = {"views": len(vs), "count": {s: len(x) for s, x in by.items()}}
    for s, x in by.items():
        if not x:
            continue
        out[s] = {
            "est_err_p50_p95": q([v["est_err"] for v in x]),
            "fit_err_p50_p95": q([v["fit_err"] for v in x]),
            "move_p50_p95": q([v["move"] for v in x]),
            "abs_move_along_axis_p50": q([abs(v["move_along_axis"]) for v in x], (0.5,)),
            "cost_ratio_p50_p95": q([(v["costs"] or {}).get("ratio") for v in x]),
            "T2_cleared_sum": int(sum(sum(t >= 1 for t in v["T2"]) for v in x)),
            "T3_cleared_sum": int(sum(sum(t >= 1 for t in v["T3"]) for v in x)),
        }
    blind = by["blind"]
    if blind:
        out["blind"]["localiser_better_than_fit"] = float(
            np.mean([v["est_err"] < v["fit_err"] for v in blind])
        )
        out["blind"]["localiser_err_gt_C1_margin"] = int(
            sum(v["est_err"] > v.get("C1_margin_xy", 0) for v in blind)
        )
        out["blind"]["C1_occupied_cleared"] = int(
            sum(bool(v.get("C1_occupied_cleared")) for v in blind)
        )
    return out


def decomposition(rows: list[dict]) -> dict:
    """Absent episodes: what clears the zone (§1.2) and why Rule's budget 5 did not (§1.3)."""
    absent = [r for r in rows if r["state"] == "absent"]
    cats = Counter()
    path_cats = Counter()
    per = {}
    full = {k: 0 for k in ("T0", "T1", "T2", "T3", "C1")}
    b5 = {k: 0 for k in ("T0", "T1", "T2", "T3", "C1")}
    for r in absent:
        v = r["views"]
        path = set(r["rule_b5"]["views"])
        c13 = {k: cleared(v, k) for k in ("T0", "T1", "T2", "T3")}
        c13["C1"] = cleared(v, "T3", blind_as="C1")
        c5 = {k: cleared(v, k, path) for k in ("T0", "T1", "T2", "T3")}
        c5["C1"] = cleared(v, "T3", path, blind_as="C1")
        for k in full:
            full[k] += bool(c13[k].all())
            b5[k] += bool(c5[k].all())
        if r["rule_b5"]["decision"] == "absent":
            continue
        if not c13["T0"].all():
            cat = "structural"
        elif not c13["T1"].all():
            cat = "depth-noise"
        elif not c13["T2"].all():
            cat = "margin"
        elif not c13["T3"].all():
            cat = "localisation-handling"
        else:
            cat = "selection-or-budget"
        cats[cat] += 1
        # path level (Rule's own views, fixed): would the same views clear with the true pose?
        if c5["T2"].all() and any(x["status"] == "blind" for x in v if x["vp"] in path):
            path_cats["path-views-blinded"] += 1
        elif c5["T2"].all():
            path_cats["path-margin-or-pose-error"] += 1
        elif c5["T1"].all():
            path_cats["path-margin"] += 1
        elif c5["T0"].all():
            path_cats["path-depth-noise"] += 1
        else:
            path_cats["path-not-observable-from-these-views"] += 1
        per[r["episode"]] = {
            "category": cat,
            "b5_path_cleared_with_true_pose_T2": bool(c5["T2"].all()),
            "b5_path_cleared_with_C1": bool(c5["C1"].all()),
            "uncleared_T3_13views": int((~c13["T3"]).sum()),
            "blind_views": sum(x["status"] == "blind" for x in v),
            "blind_views_on_path": sum(x["status"] == "blind" for x in v if x["vp"] in path),
        }
    return {
        "absent_episodes": len(absent),
        "rule_b5_absent": sum(r["rule_b5"]["decision"] == "absent" for r in absent),
        "fully_cleared_13_views": full,
        "fully_cleared_rule_b5_path_fixed": b5,
        "failure_categories": dict(cats),
        "failure_categories_rule_path": dict(path_cats),
        "failures": per,
    }


FALLBACK_M = 0.10  # v3's failed-fit margin max(10 cm, 3 sigma) - the margin a candidate would use


def candidate_offline(rows: list[dict], c: float) -> dict:
    """Upper-bound estimate, Rule's path held fixed: blind views with cost ratio <= c use the
    localiser pose (C1: margin max(6 cm, 3 sigma), slightly optimistic vs FALLBACK_M).
    Returns rescued absent failures and the risk counts on accepted views."""
    rescued = 0
    acc = risky = occ = 0
    for r in rows:
        v = r["views"]
        for x in v:
            if _accepted(x, c):
                acc += 1
                risky += x["est_err"] > max(FALLBACK_M, x.get("C1_margin_xy", 0.0))
                occ += bool(x.get("C1_occupied_cleared"))
        if r["state"] != "absent" or r["rule_b5"]["decision"] == "absent":
            continue
        path = set(r["rule_b5"]["views"])
        sub = [dict(x, C1x=x["C1"]) if _accepted(x, c) else x for x in v]
        rescued += bool(cleared(sub, "T3", path, blind_as="C1x").all())
    return {
        "accepted_blind_views": acc,
        "accepted_localiser_err_gt_margin": risky,
        "accepted_C1_occupied_cleared": occ,
        "absent_failures_rescued_path_fixed": rescued,
    }


def _accepted(x: dict, c: float) -> bool:
    return x["status"] == "blind" and bool(x["costs"]) and x["costs"]["ratio"] <= c


def discriminator(rows_by_cond: dict[str, list[dict]]) -> dict:
    """Conflict views: does the localiser-fit cost ratio separate 'fit wrong' (P0, localiser
    exact) from 'localiser wrong' (L2 reported as L1)? Diagnostic only."""
    out = {}
    for cond, rows in rows_by_cond.items():
        blind = [v for r in rows for v in r["views"] if v["status"] == "blind" and v["costs"]]
        if not blind:
            continue
        ratio = np.array([v["costs"]["ratio"] for v in blind], float)
        loc_wrong = np.array([v["est_err"] > v.get("C1_margin_xy", 0.06) for v in blind])
        out[cond] = {
            "blind_views": len(blind),
            "localiser_wrong_beyond_C1_margin": int(loc_wrong.sum()),
            "accepted_if_ratio_le": {
                str(c): {
                    "accepted": int((ratio <= c).sum()),
                    "accepted_with_localiser_wrong": int(((ratio <= c) & loc_wrong).sum()),
                }
                for c in (1.05, 1.1, 1.2, 1.3, 1.5)
            },
            "ratio_p50_p95_localiser_ok": q(ratio[~loc_wrong]),
            "ratio_p50_p95_localiser_wrong": q(ratio[loc_wrong]),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.d3p0.summarize")
    ap.add_argument("runs")
    ap.add_argument("--ns", default="v3-dev")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    from ..seal import refuse_pinned

    refuse_pinned(Path(args.out) / "summary.json")
    rows = {}
    for c in COND_ORDER:
        p = Path(args.runs) / f"{args.ns}-{c}.jsonl"
        if p.exists():
            rows[c] = load(p)
    rep = {
        "protocol": "decision 037 §1 (development data only; ground truth for attribution only)",
        "ns": args.ns,
        "view_level": {c: view_level(r) for c, r in rows.items()},
        "decomposition": {c: decomposition(r) for c, r in rows.items()},
        "discriminator": discriminator(rows),
        "candidate_offline": {
            cond: {str(c): candidate_offline(r, c) for c in (1.2, 1.3, 1.5)}
            for cond, r in rows.items()
        },
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(rep, indent=1) + "\n")
    for c, d in rep["decomposition"].items():
        print(c, "b5 absent", d["rule_b5_absent"], "/", d["absent_episodes"], "| 13-view cleared",
              d["fully_cleared_13_views"], "| failures", d["failure_categories"],
              "| on Rule's path", d["failure_categories_rule_path"])  # fmt: skip
    for c, d in rep["candidate_offline"].items():
        print(c, json.dumps(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
