"""detector-v2: dev selection and the formal test (decision 027), run once after training.

    # 1. dev, every trained config (real photos + simulator dev frames), then the §4 rule:
    uv run --extra detectors python -m activeperception.detv2.formal dev
    uv run python -m activeperception.detv2.formal select
    # 2. the formal test with the selected weights (refuses to run twice):
    uv run --extra detectors python -m activeperception.detv2.formal test --out results/detv2

Real photos are scored at the camera-equivalent size; simulator frames are the clean RGB of the
rendered episodes. Thresholds are the frozen decision-v2 ones throughout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import r0a
from . import evaluate as ev

RUNS = Path("runs/detv2")
DEV_SIM = "v3-dev"  # simulator development frames (decision 027 §4)
FORMAL_SIM = "detv2-sim"  # new namespace, rendered after the protocol froze (§5)
RECALL_DROP_DEV = 0.03  # §4 (1)
SIM_RECALL_DROP = 0.01  # §4 (2) / T3
SIM_BLOCKED_RISE = 0.01  # §4 (2)
NONINFERIOR = 0.05  # T2
T1_MAX = 0.01  # T1 = R0a A2


def sim_cache(frames: str, weights: str | None, out: Path) -> Path:
    """Detection cache over a frame store (same format as detector.run)."""
    from ..detector.cache import DetectionCache
    from ..framestore import FrameStore

    if out.exists():
        return out
    det = ev.detector(weights, "cpu")
    store = FrameStore(frames)
    name = "frcnn-mnv3" if weights is None else "frcnn-mnv3-detv2"
    cache = DetectionCache(name, {"weights": weights or "detector-v1", "frames": frames})
    for eid in store.episode_ids():
        fr = store.episode(eid)
        for vid in fr.viewpoint_ids:
            cache.put(eid, vid, det.detect(fr.rgb(vid)))
    out.parent.mkdir(parents=True, exist_ok=True)
    cache.save(out)
    return out


def dev(configs: list[str]) -> None:
    rows = r0a.read_csv(Path("data/detv2/dev.csv"))
    for c in configs:
        w = RUNS / c / "weights.pth"
        if not (RUNS / c / "dev.jsonl").exists():
            ev.detect(rows, Path("data/raw/detv2"), str(w), RUNS / c / "dev.jsonl", "cpu")
        sim_cache(f"renders/{DEV_SIM}", str(w), RUNS / c / f"{DEV_SIM}.jsonl")


def select(configs: list[str]) -> dict:
    """decision 027 §4: constraints, then the lowest dev false present on verified negatives."""
    rows = r0a.read_csv(Path("data/detv2/dev.csv"))
    ep = Path(f"data/episodes/gazebo-{DEV_SIM}.json")
    v1_real = ev.real(rows, ev.load(RUNS / "dev-v1.jsonl"))
    v1_sim = ev.sim(ep, Path(f"runs/{DEV_SIM}/detector-v1.jsonl"))
    pos_rate = _pos_rate(v1_real)
    out = {"v1": {"pos_present": pos_rate, "sim": v1_sim}, "candidates": {}}
    for c in configs:
        real = ev.real(rows, ev.load(RUNS / c / "dev.jsonl"))
        sim = ev.sim(ep, RUNS / c / f"{DEV_SIM}.jsonl")
        ok = (
            _pos_rate(real) >= pos_rate - RECALL_DROP_DEV
            and sim["visible_present"]["rate"]
            >= v1_sim["visible_present"]["rate"] - SIM_RECALL_DROP
            and sim["absent_false_present"]["k"] == 0
            and sim["absent_blocked"]["rate"] <= v1_sim["absent_blocked"]["rate"] + SIM_BLOCKED_RISE
        )
        out["candidates"][c] = {
            "eligible": ok,
            "pos_present": _pos_rate(real),
            "verified_fp": real["neg:verified"]["present"]["rate"],
            "lookalike_fp": real["neg:lookalike-all"]["present"]["rate"],
            "sim": sim,
        }
    ok = {c: v for c, v in out["candidates"].items() if v["eligible"]}
    out["selected"] = (
        min(ok, key=lambda c: (ok[c]["verified_fp"], ok[c]["lookalike_fp"])) if ok else None
    )
    return out


def _pos_rate(real: dict) -> float:
    k = sum(real[g]["present"]["k"] for g in real if g.startswith("pos:"))
    n = sum(real[g]["present"]["n"] for g in real if g.startswith("pos:"))
    return k / n


def verdicts(real1: dict, real2: dict, sim1: dict, sim2: dict, pipeline: dict | None) -> dict:
    t2 = {}
    for g, key in (("pos:boxed", "found"), ("pos:image-level", "present")):
        d = real2[g][key]["rate"] - real1[g][key]["rate"]
        t2[g] = {"v2_minus_v1": d, "pass": d >= -NONINFERIOR}
    return {
        "T1": {
            "pass": real2["neg:verified"]["present"]["rate"] <= T1_MAX,
            "false_present": real2["neg:verified"]["present"],
        },
        "T2": {"pass": all(v["pass"] for v in t2.values()), **t2},
        "T3": {
            "pass": sim2["visible_present"]["rate"]
            >= sim1["visible_present"]["rate"] - SIM_RECALL_DROP
            and sim2["absent_false_present"]["k"] == 0,
        },
        "T4": pipeline,
        "T5": "report only (report.json: real / paired / sim)",
    }


def test(out: Path, weights: str) -> int:
    if (out / "report.json").exists():
        sys.exit(
            f"{out}/report.json exists: the formal detector-v2 run is done once (decision 027)"
        )
    from .data import download

    rows = r0a.read_csv(Path("data/detv2/test.csv"))
    images = Path("data/raw/detv2")
    fetched = download(rows, images)
    raw = RUNS / "test"
    ev.detect(rows, images, None, raw / "test-v1.jsonl", "cpu")
    ev.detect(rows, images, weights, raw / "test-v2.jsonl", "cpu")
    v1, v2 = ev.load(raw / "test-v1.jsonl"), ev.load(raw / "test-v2.jsonl")
    ep = Path(f"data/episodes/gazebo-{FORMAL_SIM}.json")
    c1 = sim_cache(f"renders/{FORMAL_SIM}", None, raw / f"{FORMAL_SIM}-v1.jsonl")
    c2 = sim_cache(f"renders/{FORMAL_SIM}", weights, raw / f"{FORMAL_SIM}-v2.jsonl")
    real1, real2 = ev.real(rows, v1), ev.real(rows, v2)
    sim1, sim2 = ev.sim(ep, c1), ev.sim(ep, c2)
    report = {
        "decision": "027",
        "weights": weights,
        "download": fetched,
        "real": {"v1": real1, "v2": real2, "paired": ev.paired_real(rows, v1, v2)},
        "sim": {"v1": sim1, "v2": sim2},
        "verdicts": verdicts(real1, real2, sim1, sim2, None),
        "note": "T4 (full v3 pipeline with detector-v2) is run separately: v3.eval on "
        f"{FORMAL_SIM} with the v2 cache",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["verdicts"], indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detv2.formal")
    ap.add_argument("action", choices=["dev", "select", "test"])
    ap.add_argument("--configs", default="base,lowlr,negheavy")
    ap.add_argument("--out", default="results/detv2")
    args = ap.parse_args(argv)
    configs = args.configs.split(",")
    if args.action == "dev":
        dev(configs)
        return 0
    if args.action == "select":
        res = select(configs)
        (RUNS / "selection.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({k: res[k] for k in ("selected",)}, indent=1))
        return 0
    sel = json.loads((RUNS / "selection.json").read_text())
    if not sel["selected"]:
        sys.exit("no config met decision 027 §4 on dev: detector-v2 is not adopted")
    return test(Path(args.out), str(RUNS / sel["selected"] / "weights.pth"))


if __name__ == "__main__":
    raise SystemExit(main())
