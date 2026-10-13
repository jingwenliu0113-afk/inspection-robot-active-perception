"""Detector-selection metrics and the pre-registered selection rule (decision 005).

Inputs: the ``detsel`` episode set (refuses any other split), its frame store (labels give
the per-frame GT) and one detection cache per candidate. Mac CPU / MPS benchmark-only
caches (``run --bench-only``) can be added for the latency table and the tie-break.

    python -m activeperception.detector.evaluate --episodes data/episodes/gazebo-detsel.json \\
        --frames renders/detsel --caches runs/detsel/*.jsonl --out results/detector-selection
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..framestore import FrameStore
from ..serialize import load_episode_set
from ..sim.replay import GazeboReplayWorld
from ..types import Split
from .cache import DetectionCache

VIS_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0))
OCCLUSION_BINS = ((0.25, 0.5), (0.5, 0.75))  # S1
FP_RATE = 0.05
AP_MIN_VIS_FRACTION = 0.1
AP_MIN_VISIBLE_PX = 100
P_TIE = 0.01
S1_TIE = 0.02


@dataclass(frozen=True)
class FrameGT:
    episode_id: str
    vp_id: int
    scene_group: int
    present: bool
    visibility: float
    vis_fraction: float
    visible_px: int
    bbox_visible: tuple[int, int, int, int] | None


def frame_ground_truth(episodes_path: str | Path, frames: str | Path) -> list[FrameGT]:
    specs, _, _ = load_episode_set(episodes_path)
    bad = sorted({str(s.split) for s in specs if s.split != Split.DETSEL})
    if bad:
        raise SystemExit(f"detector selection only runs on the detsel split, got {bad}")
    world = GazeboReplayWorld(FrameStore(frames), None)
    rows = []
    for s in specs:
        for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
            lv = world.object_visibility(s, vp)
            rows.append(
                FrameGT(
                    s.episode_id,
                    vp.id,
                    s.scene_group,
                    s.layout.object_present,
                    0.0 if lv is None else lv.visibility,
                    0.0 if lv is None else lv.vis_fraction,
                    0 if lv is None else lv.visible_px,
                    None if lv is None else lv.bbox_visible,
                )
            )
    return rows


def auroc(pos: np.ndarray, neg: np.ndarray) -> float | None:
    """P(score_pos > score_neg) + 0.5 P(tie) (Mann-Whitney)."""
    if len(pos) == 0 or len(neg) == 0:
        return None
    scores = np.concatenate([pos, neg])
    order = scores.argsort(kind="mergesort")
    ranks = np.empty(len(scores))
    sorted_scores = scores[order]
    i = 0
    while i < len(scores):
        j = i
        while j + 1 < len(scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    r_pos = ranks[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)))


def fpr_threshold(neg: np.ndarray, rate: float = FP_RATE) -> float:
    """Smallest threshold t (detections need conf > t) with absent false-alarm rate <= rate."""
    if len(neg) == 0:
        return 0.0
    k = int(math.floor(rate * len(neg)))
    desc = np.sort(neg)[::-1]
    return float(desc[k]) if k < len(desc) else 0.0


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def average_precision(rows: list[FrameGT], dets: dict[tuple[str, int], list]) -> float | None:
    """VOC all-point AP at IoU 0.5; one GT box per eligible present frame."""
    eligible = [
        r
        for r in rows
        if not r.present
        or (r.vis_fraction >= AP_MIN_VIS_FRACTION and r.visible_px >= AP_MIN_VISIBLE_PX)
    ]
    n_gt = sum(1 for r in eligible if r.present)
    if n_gt == 0:
        return None
    pool = []
    for r in eligible:
        for d in dets[(r.episode_id, r.vp_id)]:
            pool.append((d[0], r, d[1:5]))
    pool.sort(key=lambda x: -x[0])
    matched: set[tuple[str, int]] = set()
    tp = np.zeros(len(pool))
    for i, (_, r, box) in enumerate(pool):
        key = (r.episode_id, r.vp_id)
        if r.present and key not in matched and iou(box, r.bbox_visible) >= 0.5:
            tp[i] = 1.0
            matched.add(key)
    if not len(pool):
        return 0.0
    ctp = np.cumsum(tp)
    recall = ctp / n_gt
    precision = ctp / np.arange(1, len(pool) + 1)
    mrec = np.concatenate([[0.0], recall, [1.0]])
    mpre = np.concatenate([[1.0], precision, [0.0]])
    mpre = np.maximum.accumulate(mpre[::-1])[::-1]
    idx = np.flatnonzero(mrec[1:] != mrec[:-1])
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def _bin_mask(vf: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (vf >= lo) & ((vf < hi) if hi < 1.0 else (vf <= hi))


def frame_metrics(rows: list[FrameGT], dets: dict[tuple[str, int], list]) -> dict:
    present = np.array([r.present for r in rows])
    vis = np.array([r.visibility for r in rows])
    vf = np.array([r.vis_fraction for r in rows])
    maxc = np.array([max((d[0] for d in dets[(r.episode_id, r.vp_id)]), default=0.0) for r in rows])
    neg = maxc[~present]
    tau5 = fpr_threshold(neg)
    out = {
        "n_frames": len(rows),
        "n_present": int(present.sum()),
        "n_absent": int((~present).sum()),
        "P_auroc": auroc(maxc[present & (vis >= 0.5)], neg),
        "tau_fpr5": tau5,
        "absent_fp_rate": {
            f"{t}": float((neg >= t).mean()) if len(neg) else None for t in (0.3, 0.5)
        },
        "absent_fp_rate_at_tau_fpr5": float((neg > tau5).mean()) if len(neg) else None,
        "absent_max_conf_quantiles": {
            q: float(np.quantile(neg, float(q))) if len(neg) else None
            for q in ("0.5", "0.9", "0.99", "1.0")
        },
        "bins": [],
    }
    recalls = []
    for lo, hi in VIS_BINS:
        m = present & _bin_mask(vf, lo, hi)
        row = {"vis_fraction": [lo, hi], "n": int(m.sum())}
        if m.any():
            row.update(
                {
                    "recall_at_0.3": float((maxc[m] >= 0.3).mean()),
                    "recall_at_0.5": float((maxc[m] >= 0.5).mean()),
                    "recall_at_tau_fpr5": float((maxc[m] > tau5).mean()),
                    "mean_max_conf": float(maxc[m].mean()),
                }
            )
            if (lo, hi) in OCCLUSION_BINS:
                recalls.append(row["recall_at_tau_fpr5"])
        out["bins"].append(row)
    out["S1_occlusion_recall"] = float(np.mean(recalls)) if recalls else None
    out["S2_ap50"] = average_precision(rows, dets)
    return out


def cluster_bootstrap_ci(rows, dets, key: str, n_boot: int, seed: int = 0):
    by_group: dict[int, list[FrameGT]] = defaultdict(list)
    for r in rows:
        by_group[r.scene_group].append(r)
    groups = sorted(by_group)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        sample = [r for g in pick for r in by_group[groups[g]]]
        v = frame_metrics(sample, dets)[key]
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def select(results: dict[str, dict], cpu_p50: dict[str, float | None]) -> tuple[str, list[str]]:
    """Decision 005 rule: P, then S1 within P ties, then license, then Mac CPU p50."""
    names = sorted(results)
    best_p = max(results[n]["P_auroc"] for n in names)
    pool = [n for n in names if best_p - results[n]["P_auroc"] <= P_TIE]
    reasons = [f"P (AUROC) best {best_p:.4f}; within {P_TIE}: {pool}"]
    if len(pool) > 1:
        best_s1 = max(results[n]["S1_occlusion_recall"] for n in pool)
        pool = [n for n in pool if best_s1 - results[n]["S1_occlusion_recall"] <= S1_TIE]
        reasons.append(f"S1 best {best_s1:.4f}; within {S1_TIE}: {pool}")
    if len(pool) > 1:
        permissive = [n for n in pool if "BSD" in results[n]["license"]]
        if permissive and len(permissive) < len(pool):
            pool = permissive
            reasons.append(f"license tie-break (BSD over AGPL): {pool}")
    if len(pool) > 1:
        pool.sort(key=lambda n: (cpu_p50.get(n) is None, cpu_p50.get(n) or 0.0))
        reasons.append(f"Mac CPU p50 tie-break: {pool[0]}")
    return pool[0], reasons


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detector.evaluate")
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--caches", nargs="+", required=True, help="full-pass detection caches")
    ap.add_argument("--bench", nargs="*", default=[], help="extra benchmark-only caches")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rows = frame_ground_truth(args.episodes, args.frames)
    results: dict[str, dict] = {}
    benches: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in args.caches:
        cache = DetectionCache.load(path)
        dets = {(r.episode_id, r.vp_id): cache.raw(r.episode_id, r.vp_id) for r in rows}
        m = frame_metrics(rows, dets)
        m["P_auroc_ci95"] = cluster_bootstrap_ci(rows, dets, "P_auroc", args.n_boot)
        m["S1_ci95"] = cluster_bootstrap_ci(rows, dets, "S1_occlusion_recall", args.n_boot)
        m.update({k: cache.meta.get(k) for k in ("license", "n_params", "weights_sha256")})
        m["versions"] = cache.meta.get("versions")
        results[cache.detector] = m
        benches[cache.detector][cache.meta["device"]] = cache.meta["benchmark"]
    for path in args.bench:
        cache = DetectionCache.load(path)
        benches[cache.detector][cache.meta["device"]] = cache.meta["benchmark"]
    cpu_p50 = {n: benches[n].get("cpu", {}).get("latency_ms_p50") for n in results}
    winner, reasons = select(results, cpu_p50)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"winner": winner, "reasons": reasons, "results": results, "benchmarks": benches}
    (out / "selection.json").write_text(json.dumps(payload, indent=1))
    print(json.dumps({"winner": winner, "reasons": reasons}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
