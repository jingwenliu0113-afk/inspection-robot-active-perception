"""Real-image data for v3 (decision 024 §3): the Open Images images R0a never used.

    uv run python -m activeperception.v3.realimg split --meta data/raw/r0a/meta \\
        --coco-flickr data/raw/r0a/coco/flickr_ids.txt --r0a data/r0a/manifest-formal.csv \\
        --out data/v3
    uv run --extra detectors python -m activeperception.v3.realimg detect \\
        --manifest data/v3/realimg-dev.csv --out runs/v3-realimg/detections-dev.jsonl
    uv run python -m activeperception.v3.realimg analyze --manifest data/v3/realimg-dev.csv \\
        --detections runs/v3-realimg/detections-dev.jsonl --out runs/v3-realimg/analysis.json

- negatives: eligible verified negatives (same rules as R0a) not drawn into the R0a formal set;
- positives: verified positives that have no hydrant box (image-level only, R0a excluded them).
Each is split in half with a fixed seed: ``dev`` (development) and ``reserve`` (kept unseen for a
possible formal test - no detector may run on it before a formal spec is frozen).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .. import r0a

SEED = 20261015


def unused_rows(meta: Path, coco_flickr: set[str], r0a_formal: set[str]) -> list[dict]:
    rows = []
    for subset in ("train", "test"):
        lab, bbox, img = {
            "train": ("train-imagelabels-hydrant.csv", "train-bbox-hydrant.csv",
                      "train-images-hydrant.csv"),
            "test": ("test-annotations-human-imagelabels-boxable.csv", "test-annotations-bbox.csv",
                     "test-images-with-rotation.csv"),
        }[subset]  # fmt: skip
        pos, neg = set(), set()
        for r in r0a.read_csv(meta / lab):
            if r["LabelName"] == r0a.HYDRANT:
                (pos if r["Confidence"] == "1" else neg).add(r["ImageID"])
        boxed = {r["ImageID"] for r in r0a.read_csv(meta / bbox) if r["LabelName"] == r0a.HYDRANT}
        info = {r["ImageID"]: r for r in r0a.read_csv(meta / img) if r["ImageID"] in pos | neg}
        for label, ids in (("pos", pos - boxed), ("neg", neg - boxed)):
            for iid in sorted(ids):
                m = info.get(iid)
                if m is None or m["Rotation"] not in ("0", "0.0"):
                    continue
                if r0a.flickr_id(m["OriginalURL"]) in coco_flickr or iid in r0a_formal:
                    continue
                rows.append(
                    {
                        "image_id": iid,
                        "subset": subset,
                        "label": label,
                        "stratum": "no-box" if label == "pos" else "negative",
                        "primary_box": "",
                        "boxes": "[]",
                        "license": m["License"],
                        "author": m["Author"],
                        "original_url": m["OriginalLandingURL"] or m["OriginalURL"],
                    }
                )
    return rows


def split(rows: list[dict], seed: int = SEED) -> tuple[list[dict], list[dict]]:
    dev, reserve = [], []
    rng = np.random.default_rng(seed)
    for label in ("pos", "neg"):
        sel = sorted((r for r in rows if r["label"] == label), key=lambda r: r["image_id"])
        mask = np.zeros(len(sel), dtype=bool)
        mask[rng.choice(len(sel), size=len(sel) // 2, replace=False)] = True
        dev += [r for r, m in zip(sel, mask, strict=True) if m]
        reserve += [r for r, m in zip(sel, mask, strict=True) if not m]
    return dev, reserve


def detect(rows: list[dict], images: Path, out: Path) -> None:
    """Frozen detector on the camera-equivalent version only (as R0a's primary variant)."""
    from ..detector import FROZEN_DETECTOR
    from ..detector.models import load_detector

    det = load_detector(FROZEN_DETECTOR, "models", "cpu")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for row in rows:
            p = r0a.image_path(images, row)
            if not p.exists():
                continue
            rgb, _ = r0a.load_rgb(p)
            img = r0a.camera_equivalent(rgb)
            h, w = img.shape[:2]
            dets = det.detect(img)[: r0a.KEEP_DETECTIONS]
            rec = {"image_id": row["image_id"], "variant": "camera", "width": w, "height": h,
                   "detections": [[round(v, 5) for v in d] for d in dets]}  # fmt: skip
            f.write(json.dumps(rec) + "\n")


def top_box_features(rec: dict) -> dict | None:
    """Confidence, aspect ratio (h / w) and area fraction of the most confident detection."""
    if not rec["detections"]:
        return None
    c, x1, y1, x2, y2 = rec["detections"][0]
    w, h = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
    return {"conf": c, "aspect": h / w, "area": w * h / (rec["width"] * rec["height"])}


def _rate(fs: list, n: int, cond) -> dict:
    return r0a.rate(sum(1 for f in fs if f is not None and cond(f)), n)


def _quantiles(fs: list, key: str) -> list[float] | None:
    if not fs:
        return None
    return [float(np.quantile([f[key] for f in fs], p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]


def _shape_filter(a_lo: float, a_hi: float, amin: float):
    def cond(f: dict) -> bool:
        return f["conf"] >= r0a.TAU_PRESENT and a_lo <= f["aspect"] <= a_hi and f["area"] >= amin

    return cond


def _at_least(t: float):
    return lambda f: f["conf"] >= t


def analyze(rows: list[dict], recs: dict[str, dict]) -> dict:
    """Development analysis: how far can image-only post-filters go? (no detector change)"""
    lab = {r["image_id"]: r["label"] for r in rows}
    feats = {k: top_box_features(v) for k, v in recs.items()}
    pos = [f for k, f in feats.items() if lab.get(k) == "pos"]
    neg = [f for k, f in feats.items() if lab.get(k) == "neg"]
    n_pos, n_neg = sum(lab[k] == "pos" for k in recs), sum(lab[k] == "neg" for k in recs)
    sweep = [
        {
            "threshold": t,
            "present_rate_pos": _rate(pos, n_pos, _at_least(t)),
            "false_present_neg": _rate(neg, n_neg, _at_least(t)),
        }
        for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99)
    ]
    hit_pos = [f for f in pos if f is not None and f["conf"] >= r0a.TAU_PRESENT]
    hit_neg = [f for f in neg if f is not None and f["conf"] >= r0a.TAU_PRESENT]
    shape = {
        name: {"n": len(fs), "aspect_q": _quantiles(fs, "aspect"), "area_q": _quantiles(fs, "area")}
        for name, fs in (("pos_at_0.7", hit_pos), ("neg_at_0.7", hit_neg))
    }
    grid = []
    for a_lo in (0.8, 1.0, 1.2, 1.4):
        for a_hi in (2.5, 3.0, 4.0, 99.0):
            for amin in (0.0, 0.005, 0.01, 0.02, 0.05):
                cond = _shape_filter(a_lo, a_hi, amin)
                grid.append(
                    {
                        "aspect": [a_lo, a_hi],
                        "min_area": amin,
                        "present_rate_pos": _rate(pos, n_pos, cond)["rate"],
                        "false_present_neg": _rate(neg, n_neg, cond)["rate"],
                    }
                )
    base = _rate(pos, n_pos, _at_least(r0a.TAU_PRESENT))["rate"]
    keep = [x for x in grid if x["present_rate_pos"] >= base - 0.05]
    return {
        "n": {"pos": n_pos, "neg": n_neg},
        "threshold_sweep": sweep,
        "absent_blocked_neg": _rate(neg, n_neg, _at_least(r0a.TAU_ABSENT)),
        "box_shape": shape,
        "best_image_only_filter_within_5pt_recall": min(keep, key=lambda x: x["false_present_neg"])
        if keep
        else None,
        "note": "development data (decision 024); image-level positives have no boxes",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.v3.realimg")
    ap.add_argument("action", choices=["split", "detect", "analyze"])
    ap.add_argument("--meta")
    ap.add_argument("--coco-flickr")
    ap.add_argument("--r0a")
    ap.add_argument("--manifest")
    ap.add_argument("--detections")
    ap.add_argument("--images", default="data/raw/r0a/images")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.action == "detect":
        if "reserve" in args.manifest:
            raise SystemExit(
                "the reserve half stays unseen until a formal spec is frozen (decision 024)"
            )
        detect(r0a.read_csv(Path(args.manifest)), Path(args.images), Path(args.out))
        return 0
    if args.action == "analyze":
        recs = r0a.load_detections(Path(args.detections))["camera"]
        res = analyze(r0a.read_csv(Path(args.manifest)), recs)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=1) + "\n")
        print(
            json.dumps(
                {
                    k: res[k]
                    for k in ("n", "absent_blocked_neg", "best_image_only_filter_within_5pt_recall")
                },
                indent=1,
            )
        )
        for row in res["threshold_sweep"]:
            print(
                row["threshold"],
                round(row["present_rate_pos"]["rate"], 3),
                round(row["false_present_neg"]["rate"], 3),
            )
        return 0
    coco = {ln.strip() for ln in open(args.coco_flickr) if ln.strip()}
    used = {r["image_id"] for r in r0a.read_csv(Path(args.r0a))}
    dev, reserve = split(unused_rows(Path(args.meta), coco, used))
    out = Path(args.out)
    r0a.write_manifest(dev, out / "realimg-dev.csv")
    r0a.write_manifest(reserve, out / "realimg-reserve.csv")
    audit = {
        name: dict(Counter(r["label"] for r in rows))
        for name, rows in (("dev", dev), ("reserve", reserve))
    }
    (out / "realimg-split.json").write_text(json.dumps(audit, indent=1) + "\n")
    print(audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
