"""detector-v2 evaluation (decision 027): real photos and simulator frames, v1 vs v2 paired.

    # real photos (camera-equivalent size, as R0a / v3):
    uv run --extra detectors python -m activeperception.detv2.evaluate detect \\
        --manifest data/detv2/dev.csv --weights runs/detv2/base/weights.pth \\
        --out runs/detv2/dev-v2.jsonl
    uv run python -m activeperception.detv2.evaluate real --manifest data/detv2/dev.csv \\
        --v1 runs/detv2/dev-v1.jsonl --v2 runs/detv2/dev-v2.jsonl
    # simulator frames (detection caches from activeperception.detector.run / detect-frames):
    uv run python -m activeperception.detv2.evaluate sim \\
        --episodes data/episodes/gazebo-v3-dev.json \\
        --v1 runs/v3-dev/detector-v1.jsonl --v2 runs/detv2/v3-dev-v2.jsonl

Thresholds are the frozen ``decision-v2`` ones (present >= 0.7, absent needs < 0.02); a detection
"finds" a boxed hydrant when it is >= 0.7 and overlaps a box with IoU >= 0.5 (R0a).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .. import r0a
from .data import image_path

TAU_PRESENT, TAU_ABSENT = r0a.TAU_PRESENT, r0a.TAU_ABSENT


def load_finetuned(weights: Path, device: str):
    """detector-v1's wrapper with fine-tuned weights (same class list and output format)."""
    import dataclasses

    from ..detector.models import CANDIDATES, TorchvisionFRCNN, sha256_file

    base = CANDIDATES["frcnn-mnv3"]
    cand = dataclasses.replace(
        base, name="frcnn-mnv3-detv2", weights=weights.name, sha256=sha256_file(weights)
    )
    return TorchvisionFRCNN(cand, weights, device)


def detector(weights: str | None, device: str):
    from ..detector import FROZEN_DETECTOR
    from ..detector.models import load_detector, resolve_device

    device = resolve_device(device)
    if weights is None:
        return load_detector(FROZEN_DETECTOR, "models", device)
    return load_finetuned(Path(weights), device)


def detect(rows: list[dict], images: Path, weights: str | None, out: Path, device: str) -> None:
    det = detector(weights, device)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for row in rows:
            p = image_path(images, row)
            if not p.exists():
                continue
            rgb, _ = r0a.load_rgb(p)
            img = r0a.camera_equivalent(rgb)
            h, w = img.shape[:2]
            dets = det.detect(img)[: r0a.KEEP_DETECTIONS]
            rec = {
                "image_id": row["image_id"],
                "source": row["source"],
                "scale": w / rgb.shape[1],
                "width": w,
                "height": h,
                "detections": [[round(v, 5) for v in d] for d in dets],
            }
            f.write(json.dumps(rec) + "\n")


def load(path: Path) -> dict[str, dict]:
    out = {}
    for ln in open(path):
        r = json.loads(ln)
        out[f"{r['source']}:{r['image_id']}"] = r
    return out


def found(row: dict, rec: dict) -> bool:
    """A detection >= 0.7 overlapping a ground-truth box (IoU >= 0.5)."""
    from .train import boxes_px

    gt = boxes_px(row, rec["scale"], rec["width"], rec["height"])
    return any(
        d[0] >= TAU_PRESENT and any(r0a.iou(d[1:], list(b)) >= r0a.IOU_MIN for b in gt)
        for d in rec["detections"]
    )


def outcomes(row: dict, rec: dict) -> dict:
    c = rec["detections"][0][0] if rec["detections"] else 0.0
    out = {"present": c >= TAU_PRESENT, "blocks_absent": c >= TAU_ABSENT, "max_conf": c}
    if row["label"] == "pos" and row["kind"] == "boxed":
        out["found"] = found(row, rec)
    return out


def group_of(row: dict) -> str:
    if row["label"] == "pos":
        return f"pos:{row['kind']}"
    return "neg:verified" if row["kind"] == "verified-negative" else f"neg:{row['category']}"


def real(rows: list[dict], recs: dict[str, dict | None]) -> dict:
    """Per group: present / found rates (positives), false present / absent blocked (negatives)."""
    acc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rec = recs.get(f"{row['source']}:{row['image_id']}")
        if rec is not None:
            acc[group_of(row)].append(outcomes(row, rec))
    res = {}
    for g, xs in sorted(acc.items()):
        n = len(xs)
        res[g] = {"n": n, "present": r0a.rate(sum(x["present"] for x in xs), n)}
        if g.startswith("neg"):
            res[g]["absent_blocked"] = r0a.rate(sum(x["blocks_absent"] for x in xs), n)
        if g == "pos:boxed":
            res[g]["found"] = r0a.rate(sum(x["found"] for x in xs), n)
    negs = [x for g, xs in acc.items() if g.startswith("neg:") and g != "neg:verified" for x in xs]
    if negs:
        res["neg:lookalike-all"] = {
            "n": len(negs),
            "present": r0a.rate(sum(x["present"] for x in negs), len(negs)),
        }
    return res


def _good(row: dict, o: dict) -> bool:
    if row["label"] == "pos":
        return o.get("found", o["present"])
    return not o["present"]


def paired_real(rows: list[dict], v1: dict, v2: dict) -> dict:
    """Images whose outcome changed between v1 and v2 (same images)."""
    out = defaultdict(lambda: {"fixed": 0, "broken": 0, "n": 0})
    for row in rows:
        k = f"{row['source']}:{row['image_id']}"
        if k not in v1 or k not in v2:
            continue
        a, b = (_good(row, outcomes(row, v[k])) for v in (v1, v2))
        g = out[group_of(row)]
        g["n"] += 1
        g["fixed"] += b and not a
        g["broken"] += a and not b
    return dict(out)


def sim(episodes: Path, cache_path: Path, visible_min: float = 0.5) -> dict:
    """Simulator frames: views where the hydrant is clearly visible (GT visibility score >=
    ``visible_min``) should give >= 0.7; views of absent episodes should stay < 0.7 / < 0.02."""
    from ..detector.cache import DetectionCache
    from ..serialize import load_episode_set

    specs, gts, _ = load_episode_set(episodes)
    cache = DetectionCache.load(cache_path)
    vis, absent = [], []
    for s in specs:
        g = gts[s.episode_id]
        views = {s.initial_viewpoint.id: g.visibility_initial, **g.visibility_by_viewpoint}
        for vp, score in views.items():
            raw = cache.raw(s.episode_id, vp)
            c = raw[0][0] if raw else 0.0
            if not g.object_present:
                absent.append(c)
            elif score >= visible_min:
                vis.append(c)
    return {
        "visible_views": len(vis),
        "visible_present": r0a.rate(sum(c >= TAU_PRESENT for c in vis), len(vis)),
        "absent_views": len(absent),
        "absent_false_present": r0a.rate(sum(c >= TAU_PRESENT for c in absent), len(absent)),
        "absent_blocked": r0a.rate(sum(c >= TAU_ABSENT for c in absent), len(absent)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detv2.evaluate")
    ap.add_argument("action", choices=["detect", "real", "sim"])
    ap.add_argument("--manifest")
    ap.add_argument("--images", default="data/raw/detv2")
    ap.add_argument("--weights", help="fine-tuned weights; omit for the frozen detector-v1")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--episodes")
    ap.add_argument("--v1")
    ap.add_argument("--v2")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    if args.action == "detect":
        if "test" in Path(args.manifest).name:
            raise SystemExit("the test manifest runs only through the formal script (decision 027)")
        rows = r0a.read_csv(Path(args.manifest))
        detect(rows, Path(args.images), args.weights, Path(args.out), args.device)
        return 0
    if args.action == "real":
        rows = r0a.read_csv(Path(args.manifest))
        res = {"v1": real(rows, load(Path(args.v1)))}
        if args.v2:
            v2 = load(Path(args.v2))
            res |= {"v2": real(rows, v2), "paired": paired_real(rows, load(Path(args.v1)), v2)}
    else:
        res = {"v1": sim(Path(args.episodes), Path(args.v1))}
        if args.v2:
            res["v2"] = sim(Path(args.episodes), Path(args.v2))
    text = json.dumps(res, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
