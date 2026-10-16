"""H-P development report (decision 037 appendix A): B0's reproducibility, safety and its proxy,
paired differences against B0, the pre-registered judgment, failure cases and compute cost.

    uv run python -m activeperception.v6.devreport runs/hp-dev --out results/hp-dev

Failure cases are replayed (Rule's path is not stored in the run files): every absent episode HP-1.2
misses at budget 5 under D3xP0, and every episode B0 gets right and HP-1.2 wrong. Ground truth is
used for scoring and attribution only. Development numbers.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..v3.formal import correct
from ..v4.devreport import summarize
from .configs import ARMS
from .dev import CONDITIONS, NAMESPACES, ONLY, file_name

SEEK = {"v3-dev": "runs/v5-dev/seek", "v3-dev-dx": "runs/v5-dev/seek-dx"}  # earlier v5 dev runs
COMPARED = (  # everything a run reports except its label
    "summary",
    "all_views_geometric_risk",
    "occupied_false_clearance",
    "views",
    "rule_per_episode",
)
MAIN, SENS = "HP12", "HP13"
G1_MIN = 0.10
BUDGETS = (2, 3, 5)


def load(root: Path) -> dict[tuple[str, str, str], dict]:
    out = {}
    for ns in NAMESPACES:
        for cond in CONDITIONS:
            for arm in ARMS:
                if arm in ONLY and cond not in ONLY[arm]:
                    continue
                f = root / ns / file_name(cond, arm)
                if f.exists():
                    out[(ns, cond, arm)] = json.loads(f.read_text())
    return out


def expected_keys() -> list[tuple[str, str, str]]:
    return [
        (ns, cond, arm)
        for ns in NAMESPACES
        for cond in CONDITIONS
        for arm in ARMS
        if not (arm in ONLY and cond not in ONLY[arm])
    ]


def reproduction(res: dict) -> dict[str, str]:
    """B0 against the earlier frozen-v5 development runs (A.2: must be identical)."""
    out = {}
    for (ns, cond, arm), r in sorted(res.items()):
        if arm != "B0":
            continue
        ref = Path(SEEK[ns]) / f"{cond.replace(':', '_')}-v4+k14.json"
        if not ref.exists():
            out[f"{ns}:{cond}"] = "no earlier run"
            continue
        old = json.loads(ref.read_text())
        same = all(json.dumps(r[k]) == json.dumps(old[k]) for k in COMPARED)
        out[f"{ns}:{cond}"] = "identical" if same else "DIFFERS"
    return out


def groups(ns: str) -> dict[str, int]:
    from ..serialize import load_episode_set

    specs, _, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    return {s.episode_id: s.scene_group for s in specs}


def safe(c: dict) -> bool:
    return c["FA"] == c["FP"] == c["GR"] == c["allview"] == c["occ"] == 0


def hp_views(r: dict) -> dict | None:
    """The conflict views H-P evaluated and accepted, and the safety proxy on the accepted."""
    v = r["views"]
    if not any("hp_ratio" in x for x in v):
        return None
    ev = [x for x in v if x["hp_ratio"] is not None]
    acc = [x for x in v if x["hp_trusted"]]
    ratios = np.array([x["hp_ratio"] for x in ev]) if ev else np.array([np.nan])
    return {
        "evaluated": len(ev),
        "accepted": len(acc),
        "accepted_exceed_xy": sum(x["err_xy"] > x["margin_xy"] for x in acc),
        "accepted_exceed_yaw": sum(x["err_yaw"] > x["margin_yaw"] for x in acc),
        "accepted_err_xy_max": max((x["err_xy"] for x in acc), default=None),
        "accepted_err_over_margin_max": max(
            (x["err_xy"] / x["margin_xy"] for x in acc), default=None
        ),
        "accepted_err_xy_over_6cm": sum(x["err_xy"] > 0.06 for x in acc),
        "ratio_p50": float(np.nanmedian(ratios)),
        # rule of three: 0 exceedances in n views -> rate < 3 / n (95 %), views taken as independent
        "exceed_rate_upper95": 3 / len(acc) if acc else None,
    }


def paired(a: dict, b: dict, grp: dict[str, int]) -> dict:
    """Arm - B0 per episode (same episodes, same draws), scene-group cluster bootstrap."""
    from ..frozen import BOOT_SEED, N_BOOT
    from ..nav.b1_analysis import cluster_bootstrap

    ea, eb = a["rule_per_episode"], b["rule_per_episode"]
    out = {}
    sets = {f"rule@{bud}": (sorted(ea), bud) for bud in BUDGETS}
    sets["absent@5"] = (sorted(e for e in ea if ea[e]["state"] == "absent"), 5)
    for name, (eids, bud) in sets.items():
        d = np.array([correct(ea[e], bud) - correct(eb[e], bud) for e in eids], float)
        g = np.array([grp[e] for e in eids])
        out[name] = cluster_bootstrap(d, g, N_BOOT, BOOT_SEED) | {
            "arm_only": int((d > 0).sum()),
            "b0_only": int((d < 0).sum()),
        }
    return out


def verdicts(summ: dict, hpv: dict, diffs: dict) -> dict:
    """Appendix A.4, on HP-1.2 only."""
    hp = [k for k in summ if k[2] == MAIN]
    complete = len(hp) == len(NAMESPACES) * len(CONDITIONS)
    s1 = complete and all(safe(summ[k]) for k in hp)
    s2 = complete and all(hpv[k]["accepted_exceed_xy"] == 0 for k in hp)
    g1 = diffs[("v3-dev", "D3xP0", MAIN)]["absent@5"]["mean"]
    r1_bad = [
        f"{k[0]}:{k[1]}@{b}" for k in hp for b in BUDGETS if diffs[k][f"rule@{b}"]["ci95"][1] < 0
    ]
    bf = [k for k in summ if k[2] == "Bfloor"]
    bf_safe = all(
        safe(summ[k]) and summ[k]["exceed"] <= summ[(k[0], k[1], "B0")]["exceed"] for k in bf
    )
    bf_as_good = all(
        summ[(ns, "D3xP0", "Bfloor")]["absent5"] >= summ[(ns, "D3xP0", MAIN)]["absent5"]
        for ns in NAMESPACES
    )
    g2 = diffs[("v3-dev-dx", "D3xP0", MAIN)]["absent@5"]["mean"]
    out = {
        "S1_safety": {"pass": s1},
        "S2_accepted_within_margin": {"pass": s2},
        "G1_absent5_gain_v3dev_D3xP0": {"value": g1, "min": G1_MIN, "pass": g1 >= G1_MIN - 1e-9},
        "R1_no_significant_loss": {"pass": complete and not r1_bad, "violations": r1_bad},
        "F1_bfloor_as_good": {
            "holds": bool(bf) and bf_safe and bf_as_good,
            "safe": bf_safe,
            "as_good": bf_as_good,
        },  # fmt: skip
        "G2_absent5_gain_v3devdx_D3xP0": {"value": g2, "in_sample_only": g2 <= 0},
    }
    ok = s1 and s2 and out["G1_absent5_gain_v3dev_D3xP0"]["pass"] and not r1_bad
    out["recommend_formal"] = bool(ok and not out["F1_bfloor_as_good"]["holds"])
    out["stop"] = not ok
    return out


# ---------------------------------------------------------------- replays (attribution only)


def _world(ns: str, cond: str, arm: str):
    from ..detector.cache import DetectionCache
    from ..framestore import FrameStore
    from ..sim.replay import GazeboReplayWorld
    from ..v3.eval import V3World

    depth, rest = cond.split("x")
    pose, prior = (rest.split(":") + [None])[:2]
    base = GazeboReplayWorld(
        FrameStore(f"renders/{ns}"), DetectionCache.load(f"runs/{ns}/detector-v1.jsonl")
    )
    return V3World(base, depth, pose, ARMS[arm], True, prior)


def replay(ns: str, cond: str, arm: str, eid: str, budget: int) -> dict:
    """Rule's path at ``budget`` and what each view on it contributed."""
    from .. import frozen_v2
    from ..harness import run_episode
    from ..sensing import cleared_locations
    from ..serialize import load_episode_set
    from ..v3.eval import DecisionRuleV3, rule_nbv_v3
    from ..v5 import frozen_v5

    specs, _, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    spec = next(s for s in specs if s.episode_id == eid)
    world = _world(ns, cond, arm)
    rule = DecisionRuleV3(frozen_v2.DECISION_V2, version="decision-v3-dev")
    rec = run_episode(spec, world, rule_nbv_v3(frozen_v5.TIE_BREAK), rule, budget, 0)
    dep = spec.deployable()
    views = [spec.initial_viewpoint] + [dep.candidate(v) for v in rec.viewpoint_sequence[1:]]
    every = (spec.initial_viewpoint, *spec.candidate_viewpoints)
    path = []
    for vp in views:
        obs = world.observe(spec, vp)
        d = world.diag[(eid, vp.id)]
        path.append({
            "vp": vp.id,
            "status": "ok" if d["refine_ok"] else ("blind" if d["blind"] else
                      ("hp" if d.get("hp_trusted") else "fallback")),
            "hp_ratio": d.get("hp_ratio"),
            "err_xy": round(d["err_xy"], 4),
            "margin_xy": round(d["margin_xy"], 4),
            "cleared": int(sum(x >= 1.0 for x in obs.location_visibility)),
            "c_block": round(float(obs.meta.get("c_block", 0.0)), 4),
        })  # fmt: skip
    hist = [world.observe(spec, vp) for vp in views]
    all_hist = [world.observe(spec, vp) for vp in every]
    return {
        "decision": rec.decision.value,
        "path": path,
        "cleared_by_path": float(cleared_locations(hist, 1.0).mean()),
        "cleared_by_all_views": float(cleared_locations(all_hist, 1.0).mean()),
    }


def attribute(arm_r: dict) -> str:
    """Why an absent episode stays inconclusive (in protocol order)."""
    if any(v["c_block"] > 0.02 for v in arm_r["path"]):  # decision-v2 tau_absent
        return "detection blocks absent"
    if arm_r["cleared_by_path"] >= 1.0:
        return "cleared but not absent (rule)"
    if arm_r["cleared_by_all_views"] >= 1.0:
        blind = [v for v in arm_r["path"] if v["status"] == "blind"]
        return "path: blind views (ratio > c)" if blind else "path: view selection / budget"
    return "not clearable with every view"


def failures(res: dict) -> dict:
    out = {"hp_absent_misses": [], "b0_only": []}
    for ns in NAMESPACES:
        r = res.get((ns, "D3xP0", MAIN))
        if r is None:
            continue
        for eid, e in sorted(r["rule_per_episode"].items()):
            if e["state"] == "absent" and e["b5"] != "absent":
                a = replay(ns, "D3xP0", MAIN, eid, 5)
                out["hp_absent_misses"].append(
                    {"ns": ns, "episode": eid, "cause": attribute(a), MAIN: a,
                     "B0_b5": res[(ns, "D3xP0", "B0")]["rule_per_episode"][eid]["b5"]}
                )  # fmt: skip
    for (ns, cond, arm), r in sorted(res.items()):
        if arm != MAIN:
            continue
        b0 = res[(ns, cond, "B0")]["rule_per_episode"]
        for eid, e in sorted(r["rule_per_episode"].items()):
            for bud in BUDGETS:
                if correct(b0[eid], bud) and not correct(e, bud):
                    out["b0_only"].append({
                        "ns": ns, "cond": cond, "episode": eid, "budget": bud,
                        "state": e["state"], "B0": b0[eid][f"b{bud}"], MAIN: e[f"b{bud}"],
                        "replay": {a: replay(ns, cond, a, eid, bud) for a in ("B0", MAIN)},
                    })  # fmt: skip
    return out


def compute_cost(res: dict, n: int = 40) -> dict:
    """Time of the refinement and of the cost ratio on conflict views (v3-dev D3xP0)."""
    from ..nav.localize import map_outlines
    from ..serialize import load_episode_set
    from ..v3.eval import estimated_pose, noisy_depth, reported_prior
    from ..v4.geometry import refine_pose_v4
    from .hp import cost_ratio

    r = res[("v3-dev", "D3xP0", MAIN)]
    picks = [x for x in r["views"] if x["hp_ratio"] is not None][:n]
    specs, _, _ = load_episode_set("data/episodes/gazebo-v3-dev.json")
    by_id = {s.episode_id: s for s in specs}
    world = _world("v3-dev", "D3xP0", MAIN)
    cfg, prior = ARMS[MAIN], reported_prior("P0")
    t_ref, t_ratio = [], []
    for x in picks:
        spec = by_id[x["episode"]]
        every = (spec.initial_viewpoint, *spec.candidate_viewpoints)
        vp = next(v for v in every if v.id == x["vp"])
        depth = noisy_depth(spec, vp.id, world.base._frames(spec).depth(vp.id), "D3")
        est, outlines = estimated_pose(spec, vp, "P0"), map_outlines(spec)
        t0 = time.perf_counter()
        ref = refine_pose_v4(depth, spec.camera, est, spec.zone, outlines, cfg, prior=prior)
        t1 = time.perf_counter()
        cost_ratio(depth, spec.camera, est, spec.zone, outlines, cfg, ref)
        t2 = time.perf_counter()
        t_ref.append(t1 - t0)
        t_ratio.append(t2 - t1)
    return {
        "views": len(picks),
        "refine_ms_median": 1e3 * float(np.median(t_ref)),
        "ratio_ms_median": 1e3 * float(np.median(t_ratio)),
        "ratio_over_refine": float(np.median(np.array(t_ratio) / np.array(t_ref))),
        "note": "wall-clock on the shared Mac; not reproducible to the digit",
    }


def _f(x: float) -> str:
    return f"{x:+.3f}"


def markdown(summ, hpv, diffs, ver, rep) -> str:
    out = ["| 資料 / 條件 | 管線 | FA | FP | GR | 全視角 | 佔用看穿 | 超出餘裕 "
           "| 精修成功 / 不提供看穿 | H-P 評估 / 接受（超出） | Rule b2 / b3 / b5 | absent@5 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for k in sorted(summ, key=lambda k: (CONDITIONS.index(k[1]), k[0], list(ARMS).index(k[2]))):
        c, h = summ[k], hpv.get(k)
        hp = "—"
        if h is not None:
            hp = f"{h['evaluated']} / {h['accepted']}（{h['accepted_exceed_xy']}）"
        rule = " / ".join(f"{a:.3f}" for a in c["rule"])
        out.append(
            f"| `{k[0]}` {k[1]} | {k[2]} | {c['FA']} | {c['FP']} | {c['GR']} | {c['allview']} | "
            f"{c['occ']} | {c['exceed']} | {c['ok']} / {c['blind']} | {hp} | {rule} | "
            f"{c['absent5']:.3f} |"
        )
    out += ["", "| 資料 / 條件 | 管線 − B0 | Rule b2 | Rule b3 | Rule b5 | absent@5 |",
            "|---|---|---|---|---|---|"]  # fmt: skip
    for k in sorted(diffs, key=lambda k: (CONDITIONS.index(k[1]), k[0], list(ARMS).index(k[2]))):
        cells = []
        for name in (*(f"rule@{b}" for b in BUDGETS), "absent@5"):
            d = diffs[k][name]
            lo, hi = d["ci95"]
            n = f"（+{d['arm_only']} / −{d['b0_only']}）"
            cells.append(f"{_f(d['mean'])} [{_f(lo)}, {_f(hi)}]{n}")
        out.append(f"| `{k[0]}` {k[1]} | {k[2]} | " + " | ".join(cells) + " |")
    out += ["", "B0 可重現性：" + "、".join(f"{k} {v}" for k, v in rep.items()), ""]
    out.append("判定：" + json.dumps(ver, ensure_ascii=False))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v6.devreport")
    ap.add_argument("runs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-replay", action="store_true")
    args = ap.parse_args(argv)
    res = load(Path(args.runs))
    missing = [k for k in expected_keys() if k not in res]
    if missing:
        raise SystemExit(f"{len(missing)} runs missing, e.g. {missing[:3]}")
    rep = reproduction(res)
    if any(v == "DIFFERS" for v in rep.values()):
        raise SystemExit(f"B0 does not reproduce the earlier v5 runs: {rep}")
    grp = {ns: groups(ns) for ns in NAMESPACES}
    summ = {k: summarize(r) for k, r in res.items()}
    hpv = {k: h for k, r in res.items() if (h := hp_views(r)) is not None}
    diffs = {
        k: paired(r, res[(k[0], k[1], "B0")], grp[k[0]]) for k, r in res.items() if k[2] != "B0"
    }
    ver = verdicts(summ, hpv, diffs)
    report = {
        "protocol": "decision 037 appendix A",
        "reproduction_B0": rep,
        "runs": {":".join(k): summ[k] | ({"hp": hpv[k]} if k in hpv else {}) for k in summ},
        "paired_vs_B0": {":".join(k): v for k, v in diffs.items()},
        "verdicts": ver,
    }
    if not args.no_replay:
        report["failures"] = failures(res)
        report["compute_cost"] = compute_cost(res)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    md = markdown(summ, hpv, diffs, ver, rep)
    (out / "tables.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
