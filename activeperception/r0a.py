"""R0a (decision 020): the frozen detector on real fire-hydrant photos (Open Images V7).

    uv run python -m activeperception.r0a select --meta data/raw/r0a/meta \\
        --coco-flickr data/raw/r0a/coco/flickr_ids.txt --out data/r0a
    uv run python -m activeperception.r0a download --manifest data/r0a/manifest-dev.csv \\
        --images data/raw/r0a/images
    uv run --extra detectors python -m activeperception.r0a detect \\
        --manifest data/r0a/manifest-dev.csv --images data/raw/r0a/images \\
        --out runs/r0a/detections-dev.jsonl
    uv run python -m activeperception.r0a report --manifest data/r0a/manifest-formal.csv \\
        --detections results/r0a/detections-formal.jsonl --out results/r0a

Real photographs, **not** a robot camera and not a robot (decision 020 §2). The thresholds are
the frozen ``decision-v2`` ones and are never tuned here. Images stay in ``data/raw`` (not in
git); the manifests record ID, author, licence and original URL for attribution.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import frozen_v2

HYDRANT = "/m/01pns0"
TAU_PRESENT = frozen_v2.DECISION_V2.tau_present
TAU_ABSENT = frozen_v2.DECISION_V2.tau_absent
SMALL_AREA = 0.02  # primary box below 2% of the image -> "small"
IOU_MIN = 0.5
NEG_SAMPLE = 600
SEED = 20261014
CAMERA_PIXELS = 640 * 480  # the Core / Advanced B camera
OCCLUSION_FRACTIONS = (0.25, 0.5, 0.75)
GRAY = 128
KEEP_DETECTIONS = 20  # stored per image (sorted by confidence)
SPLITS = {"dev": ("validation",), "formal": ("train", "test")}
STRATA = ("clear", "small", "truncated", "occluded", "unknown", "group-only", "depiction")
MAIN_STRATA = ("clear", "small", "truncated", "occluded")
S3 = "https://open-images-dataset.s3.amazonaws.com/{subset}/{image_id}.jpg"
MANIFEST_FIELDS = (
    "image_id",
    "subset",
    "label",
    "stratum",
    "primary_box",
    "boxes",
    "license",
    "author",
    "original_url",
)


# ---------------------------------------------------------------- selection (metadata only)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def flickr_id(url: str) -> str:
    """Flickr photo ID from a static Flickr URL (``.../<photo>_<secret>_<size>.jpg``)."""
    return url.rsplit("/", 1)[-1].split("_", 1)[0]


def box_of(row: dict) -> dict:
    flags = {k: int(row[k]) for k in ("IsOccluded", "IsTruncated", "IsGroupOf", "IsDepiction")}
    xy = [float(row[k]) for k in ("XMin", "YMin", "XMax", "YMax")]
    return {"xyxy": xy, **flags}


def area(b: dict) -> float:
    x1, y1, x2, y2 = b["xyxy"]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def stratum(boxes: list[dict]) -> tuple[str, dict | None]:
    """decision 020 §4, in priority order; the primary box is the largest real, single one."""
    real = [b for b in boxes if b["IsDepiction"] != 1]
    if not real:
        return "depiction", None
    single = [b for b in real if b["IsGroupOf"] != 1]
    if not single:
        return "group-only", None
    p = max(single, key=area)
    if p["IsOccluded"] == 1:
        return "occluded", p
    if p["IsTruncated"] == 1:
        return "truncated", p
    if -1 in (p["IsOccluded"], p["IsTruncated"]):
        return "unknown", p
    if area(p) < SMALL_AREA:
        return "small", p
    return "clear", p


def sample_negatives(ids: list[str], n: int = NEG_SAMPLE, seed: int = SEED) -> list[str]:
    ids = sorted(ids)
    if len(ids) <= n:
        return ids
    pick = np.random.default_rng(seed).choice(len(ids), size=n, replace=False)
    return sorted(ids[i] for i in pick)


def select(meta: Path, coco_flickr: set[str]) -> tuple[dict[str, list[dict]], dict]:
    """Manifests per split from the Open Images metadata only (no detector output)."""
    labels: dict[str, dict[str, set]] = {}
    boxes: dict[str, dict[str, list]] = {}
    info: dict[str, dict[str, dict]] = {}
    files = {
        "validation": (
            "validation-annotations-human-imagelabels-boxable.csv",
            "validation-annotations-bbox.csv",
            "validation-images-with-rotation.csv",
        ),
        "test": (
            "test-annotations-human-imagelabels-boxable.csv",
            "test-annotations-bbox.csv",
            "test-images-with-rotation.csv",
        ),
        "train": (
            "train-imagelabels-hydrant.csv",
            "train-bbox-hydrant.csv",
            "train-images-hydrant.csv",
        ),
    }
    for subset, (lab, bbox, img) in files.items():
        pos, neg = set(), set()
        for r in read_csv(meta / lab):
            if r["LabelName"] == HYDRANT:
                (pos if r["Confidence"] == "1" else neg).add(r["ImageID"])
        bx = defaultdict(list)
        for r in read_csv(meta / bbox):
            if r["LabelName"] == HYDRANT:
                bx[r["ImageID"]].append(box_of(r))
        labels[subset], boxes[subset] = {"pos": pos, "neg": neg}, bx
        info[subset] = {r["ImageID"]: r for r in read_csv(meta / img) if r["ImageID"] in pos | neg}
    manifests, audit = {}, {}
    for split, subsets in SPLITS.items():
        rows, negs, why = [], [], Counter()
        for subset in subsets:
            pos, neg, bx = labels[subset]["pos"], labels[subset]["neg"], boxes[subset]
            for label, ids in (("pos", sorted(pos & set(bx))), ("neg", sorted(neg - set(bx)))):
                for iid in ids:
                    m = info[subset].get(iid)
                    if m is None:
                        why[f"{label}: no image metadata"] += 1
                    elif m["Rotation"] not in ("0", "0.0"):
                        why[f"{label}: rotation {m['Rotation'] or 'missing'}"] += 1
                    elif flickr_id(m["OriginalURL"]) in coco_flickr:
                        why[f"{label}: also in COCO 2017"] += 1
                    else:
                        st, p = stratum(bx[iid]) if label == "pos" else ("negative", None)
                        row = {
                            "image_id": iid,
                            "subset": subset,
                            "label": label,
                            "stratum": st,
                            "primary_box": json.dumps(p["xyxy"]) if p else "",
                            "boxes": json.dumps([b["xyxy"] for b in bx.get(iid, [])]),
                            "license": m["License"],
                            "author": m["Author"],
                            "original_url": m["OriginalLandingURL"] or m["OriginalURL"],
                        }
                        (rows if label == "pos" else negs).append(row)
            why[f"pos: verified but no box ({subset})"] += len(pos - set(bx))
        kept = set(sample_negatives([r["image_id"] for r in negs])) if split == "formal" else None
        rows += [r for r in negs if kept is None or r["image_id"] in kept]
        manifests[split] = rows
        audit[split] = {
            "positives": sum(r["label"] == "pos" for r in rows),
            "negatives": sum(r["label"] == "neg" for r in rows),
            "negatives_eligible": len(negs),
            "strata": dict(Counter(r["stratum"] for r in rows if r["label"] == "pos")),
            "excluded": dict(sorted(why.items())),
            "licenses": dict(Counter(r["license"] for r in rows)),
        }
    return manifests, audit


def write_manifest(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- images


def image_path(images: Path, row: dict) -> Path:
    return images / row["subset"] / f"{row['image_id']}.jpg"


def download(rows: list[dict], images: Path, workers: int = 8) -> dict:
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    def one(row):
        p = image_path(images, row)
        if p.exists():
            return row["image_id"], "cached"
        p.parent.mkdir(parents=True, exist_ok=True)
        url = S3.format(subset=row["subset"], image_id=row["image_id"])
        for k in range(5):
            try:
                data = urllib.request.urlopen(url, timeout=120).read()
                tmp = p.with_suffix(".part")
                tmp.write_bytes(data)
                with Image.open(tmp) as im:
                    im.verify()
                tmp.rename(p)
                return row["image_id"], "ok"
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(3 * (k + 1))
        return row["image_id"], f"failed: {err}"

    with ThreadPoolExecutor(workers) as ex:
        res = dict(ex.map(one, rows))
    return {
        "status": dict(Counter(v.split(":")[0] for v in res.values())),
        "failed": sorted(k for k, v in res.items() if v.startswith("failed")),
    }


def load_rgb(path: Path) -> tuple[np.ndarray, int]:
    """Decoded pixels as stored (no EXIF transpose; decision 020 keeps Rotation == 0 only)."""
    from PIL import Image

    with Image.open(path) as im:
        orient = int(im.getexif().get(0x0112, 1))
        return np.array(im.convert("RGB")), orient  # writable copy for torch


def camera_equivalent(rgb: np.ndarray) -> np.ndarray:
    """Downscale (never upscale) to about the robot camera's pixel count, aspect kept."""
    from PIL import Image

    h, w = rgb.shape[:2]
    if w * h <= CAMERA_PIXELS:
        return rgb
    s = math.sqrt(CAMERA_PIXELS / (w * h))
    size = (max(1, round(w * s)), max(1, round(h * s)))
    return np.array(Image.fromarray(rgb).resize(size, Image.Resampling.LANCZOS))


def occlusion_side(image_id: str) -> str:
    return "left" if hashlib.sha256(image_id.encode()).digest()[0] % 2 == 0 else "right"


def occlude(rgb: np.ndarray, box: list[float], fraction: float, side: str) -> np.ndarray:
    """Grey vertical band over ``fraction`` of the box width, full box height (a pillar)."""
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    bw = (x2 - x1) * fraction
    a, b = (x1, x1 + bw) if side == "left" else (x2 - bw, x2)
    out = rgb.copy()
    out[int(math.floor(y1)) : int(math.ceil(y2)), int(math.floor(a)) : int(math.ceil(b))] = GRAY
    return out


def variants(row: dict, rgb: np.ndarray, formal: bool) -> dict[str, np.ndarray]:
    cam = camera_equivalent(rgb)
    out = {"camera": cam, "original": rgb}
    if formal and row["label"] == "pos" and row["stratum"] == "clear":
        box, side = json.loads(row["primary_box"]), occlusion_side(row["image_id"])
        for f in OCCLUSION_FRACTIONS:
            out[f"occ{int(f * 100)}"] = occlude(cam, box, f, side)
    return out


def detect(rows: list[dict], images: Path, out: Path, formal: bool, device: str = "cpu") -> None:
    from .detector import FROZEN_DETECTOR
    from .detector.models import load_detector

    det = load_detector(FROZEN_DETECTOR, "models", device)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for row in rows:
            p = image_path(images, row)
            if not p.exists():
                continue
            rgb, orient = load_rgb(p)
            for name, img in variants(row, rgb, formal).items():
                h, w = img.shape[:2]
                dets = det.detect(img)[:KEEP_DETECTIONS]
                rec = {
                    "image_id": row["image_id"],
                    "variant": name,
                    "width": w,
                    "height": h,
                    "exif_orientation": orient,
                    "detections": [[round(v, 5) for v in d] for d in dets],
                }
                f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------- metrics


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": k / n if n else None, "ci95": wilson(k, n)}


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def normalised(rec: dict) -> list[list[float]]:
    w, h = rec["width"], rec["height"]
    return [[d[0], d[1] / w, d[2] / h, d[3] / w, d[4] / h] for d in rec["detections"]]


def image_outcome(row: dict, rec: dict) -> dict:
    dets = normalised(rec)
    c_max = max((d[0] for d in dets), default=0.0)
    gts = json.loads(row["boxes"])
    hit = any(d[0] >= TAU_PRESENT and any(iou(d[1:], g) >= IOU_MIN for g in gts) for d in dets)
    return {"c_max": c_max, "localized_hit": hit}


def ap50(rows: list[dict], recs: dict[str, dict]) -> float | None:
    """All-point interpolated AP at IoU 0.5 over the given images (greedy matching)."""
    n_gt, scored = 0, []
    for row in rows:
        rec = recs.get(row["image_id"])
        if rec is None:
            continue
        gts = json.loads(row["boxes"])
        n_gt += len(gts)
        used = set()
        for d in sorted(normalised(rec), key=lambda d: -d[0]):
            best, j = 0.0, None
            for k, g in enumerate(gts):
                v = iou(d[1:], g)
                if k not in used and v > best:
                    best, j = v, k
            if j is not None and best >= IOU_MIN:
                used.add(j)
                scored.append((d[0], 1))
            else:
                scored.append((d[0], 0))
    if not n_gt:
        return None
    scored.sort(key=lambda t: -t[0])
    tp = np.cumsum([s[1] for s in scored])
    fp = np.cumsum([1 - s[1] for s in scored])
    rec_ = tp / n_gt
    prec = tp / np.maximum(tp + fp, 1)
    mrec = np.concatenate([[0.0], rec_, [1.0]])
    mpre = np.concatenate([[0.0], prec, [0.0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.flatnonzero(mrec[1:] != mrec[:-1])
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def summarize(rows: list[dict], recs_by_variant: dict[str, dict[str, dict]]) -> dict:
    out: dict = {}
    for variant, recs in recs_by_variant.items():
        res: dict = {"positives": {}, "negatives": None}
        for st in (*STRATA, "main"):
            want = MAIN_STRATA if st == "main" else (st,)
            sel = [
                r
                for r in rows
                if r["label"] == "pos" and r["stratum"] in want and r["image_id"] in recs
            ]
            if not sel:
                continue
            o = [image_outcome(r, recs[r["image_id"]]) for r in sel]
            res["positives"][st] = {
                "localized_recall_at_present": rate(sum(x["localized_hit"] for x in o), len(o)),
                "present_rate": rate(sum(x["c_max"] >= TAU_PRESENT for x in o), len(o)),
                "complete_miss": rate(sum(x["c_max"] < TAU_ABSENT for x in o), len(o)),
                "c_max_quartiles": [
                    float(np.quantile([x["c_max"] for x in o], q)) for q in (0.25, 0.5, 0.75)
                ],
            }
        neg = [r for r in rows if r["label"] == "neg" and r["image_id"] in recs]
        if neg:
            c = [image_outcome(r, recs[r["image_id"]])["c_max"] for r in neg]
            res["negatives"] = {
                "false_present": rate(sum(v >= TAU_PRESENT for v in c), len(c)),
                "absent_blocked": rate(sum(v >= TAU_ABSENT for v in c), len(c)),
                "c_max_p95": float(np.quantile(c, 0.95)),
            }
        res["ap50"] = ap50([r for r in rows if r["image_id"] in recs], recs)
        out[variant] = res
    return out


def criteria(s: dict) -> dict:
    """decision 020 §7 on the camera-equivalent variant."""
    cam = s["camera"]
    a1 = cam["positives"]["clear"]["localized_recall_at_present"]
    a2, a3 = cam["negatives"]["false_present"], cam["negatives"]["absent_blocked"]
    return {
        "A1_clear_localized_recall": {**a1, "pass": a1["rate"] >= 0.90},
        "A2_false_present": {**a2, "pass": a2["rate"] <= 0.01},
        "A3_absent_blocked": {**a3, "absent_usable": a3["rate"] <= 0.10},
    }


def _pct(r: dict) -> str:
    lo, hi = r["ci95"]
    return f"{r['k']} / {r['n']} = {100 * r['rate']:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


def markdown(report: dict) -> str:
    """Tables for results/r0a/README.md (Traditional Chinese headers)."""
    s, out = report["summary"], []
    for variant, title in (
        ("camera", "約 640×480 像素數（主要）"),
        ("original", "原始解析度（參考）"),
    ):
        v = s[variant]
        out += [
            f"### 含消防栓的影像：{title}",
            "",
            "| 層 | localized recall@0.7 | present rate | complete miss（< 0.02） |",
            "|---|---|---|---|",
        ]
        for st in (*MAIN_STRATA, "main"):
            if st in v["positives"]:
                r = v["positives"][st]
                cells = (r["localized_recall_at_present"], r["present_rate"], r["complete_miss"])
                out.append(f"| {st} | " + " | ".join(_pct(c) for c in cells) + " |")
        n = v["negatives"]
        out += [
            "",
            f"不含消防栓（人工驗證、偏難的負樣本）：false present {_pct(n['false_present'])}；"
            f"absent blocked {_pct(n['absent_blocked'])}；AP50 {v['ap50']:.3f}",
            "",
        ]
    occ = sorted((k for k in s if k.startswith("occ")), key=lambda k: int(k[3:]))
    if occ:
        clear = s["camera"]["positives"]["clear"]
        out += [
            "### 人工遮擋（clear 正樣本，camera 版本）",
            "",
            "| 遮住框寬 | present rate | complete miss |",
            "|---|---|---|",
            f"| 0% | {_pct(clear['present_rate'])} | {_pct(clear['complete_miss'])} |",
        ]
        for k in occ:
            r = s[k]["positives"]["clear"]
            out.append(f"| {k[3:]}% | {_pct(r['present_rate'])} | {_pct(r['complete_miss'])} |")
        out.append("")
    c = report.get("criteria")
    if c:
        a1 = c["A1_clear_localized_recall"]
        a2, a3 = c["A2_false_present"], c["A3_absent_blocked"]
        out += [
            "### 判準（decision 020 §7）",
            "",
            "| # | 結果 | 判定 |",
            "|---|---|---|",
            f"| A1 clear localized recall@0.7 ≥ 0.90 | {_pct(a1)} | {_verdict(a1['pass'])} |",
            f"| A2 false present ≤ 0.01 | {_pct(a2)} | {_verdict(a2['pass'])} |",
            f"| A3 absent blocked（≤ 0.10 視為可用） | {_pct(a3)} "
            f"| {'可用' if a3['absent_usable'] else '**不可用**'} |",
            "",
        ]
    return "\n".join(out) + "\n"


def _verdict(ok: bool) -> str:
    return "通過" if ok else "**未通過**"


def load_detections(path: Path) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for line in open(path):
        rec = json.loads(line)
        out[rec["variant"]][rec["image_id"]] = rec
    return dict(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.r0a")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--meta", required=True)
    s.add_argument("--coco-flickr", required=True)
    s.add_argument("--out", required=True)
    d = sub.add_parser("download")
    d.add_argument("--manifest", required=True)
    d.add_argument("--images", required=True)
    r = sub.add_parser("detect")
    r.add_argument("--manifest", required=True)
    r.add_argument("--images", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--device", default="cpu")
    p = sub.add_parser("report")
    p.add_argument("--manifest", required=True)
    p.add_argument("--detections", required=True)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "select":
        coco = {ln.strip() for ln in open(args.coco_flickr) if ln.strip()}
        manifests, audit = select(Path(args.meta), coco)
        for split, rows in manifests.items():
            write_manifest(rows, Path(args.out) / f"manifest-{split}.csv")
        (Path(args.out) / "selection.json").write_text(json.dumps(audit, indent=1) + "\n")
        print(json.dumps(audit, indent=1))
    elif args.cmd == "download":
        print(json.dumps(download(read_csv(Path(args.manifest)), Path(args.images)), indent=1))
    elif args.cmd == "detect":
        out = Path(args.out)
        formal = "formal" in Path(args.manifest).name
        if formal and out.exists():
            sys.exit(f"{out} exists: the formal R0a run is done once (decision 020)")
        detect(read_csv(Path(args.manifest)), Path(args.images), out, formal, args.device)
    else:
        rows = read_csv(Path(args.manifest))
        summary = summarize(rows, load_detections(Path(args.detections)))
        report = {"summary": summary}
        if "formal" in Path(args.manifest).name:
            report["criteria"] = criteria(summary)
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "report.json").write_text(json.dumps(report, indent=1) + "\n")
        (Path(args.out) / "tables.md").write_text(markdown(report))
        print(json.dumps(report.get("criteria", summary["camera"]), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
