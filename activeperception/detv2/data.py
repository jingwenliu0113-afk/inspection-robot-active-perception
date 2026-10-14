"""detector-v2 data (decision 027): train / dev / test manifests from metadata only.

    uv run python -m activeperception.detv2.data split --out data/detv2
    uv run python -m activeperception.detv2.data download --manifest data/detv2/train.csv

Sources (images are never committed; manifests carry ID, licence, author and URL):

- positives, boxed: COCO 2017 ``fire hydrant`` images under licences that allow derivatives
  (CC BY, CC BY-SA, no known copyright). train2017 -> train, val2017 -> dev (detector-v1 was
  trained on train2017 only, so val2017 is unseen by it).
- hard negatives: Open Images images whose ``Fire hydrant`` label a human verified as absent
  (the R0a / v3 population), from the v3 development half -> split train / dev.
- look-alikes: Open Images validation / test images with boxes of classes that resemble a
  hydrant (decision 027 §2; from the v3 hard-negative categories), no hydrant label of any kind
  -> split train / dev.
- test (frozen, unseen; no detector runs on it before the protocol is frozen and the model is
  trained): the v3 real-image reserve half (verified negatives + image-level positives), the
  boxed Open Images hydrant images no earlier study used (none pass R0a's rules today), and the
  COCO val2017 hydrant images under NC / ND licences (scored only, never trained on).

Every Open Images image: CC BY 2.0, Rotation 0, not in COCO 2017 (Flickr ID). Nothing from the
R0a formal set, the R0a dev set, or the simulator.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .. import r0a

SEED = 20261016
R0A_IMAGES = Path("data/raw/r0a/images")
COCO_HYDRANT = 11
COCO_LICENCES = {  # COCO licence id -> URL; derivatives allowed
    4: "https://creativecommons.org/licenses/by/2.0/",
    5: "https://creativecommons.org/licenses/by-sa/2.0/",
    7: "no known copyright restrictions",
}
CC_BY = "https://creativecommons.org/licenses/by/2.0/"
LOOKALIKES = {  # Open Images class -> v3 hard-negative category (results/v3-dev)
    "/m/02jz0l": ("Tap", "pipe-hardware"),
    "/m/0220r2": ("Fountain", "pipe-hardware"),
    "/m/015qbp": ("Parking meter", "street-furniture"),
    "/m/033rq4": ("Street light", "street-furniture"),
    "/m/0bjyj5": ("Waste container", "street-furniture"),
    "/m/02zn6n": ("Barrel", "street-furniture"),
    "/m/0fm3zh": ("Flowerpot", "street-furniture"),
    "/m/01mqdt": ("Traffic sign", "street-furniture"),
    "/m/06msq": ("Sculpture", "figure-statue"),
    "/m/04yqq2": ("Bust", "figure-statue"),
    "/m/0167gd": ("Doll", "figure-statue"),
    "/m/0138tl": ("Toy", "figure-statue"),
    "/m/0152hh": ("Snowman", "figure-statue"),
    "/m/01fh4r": ("Teapot", "figure-statue"),
    "/m/02s195": ("Vase", "figure-statue"),
    "/m/0c06p": ("Candle", "other"),
    "/m/01jfsr": ("Lantern", "other"),
    "/m/04dr76w": ("Bottle", "other"),
    "/m/03s_tn": ("Kettle", "other"),
}
LOOKALIKE_PER_CLASS = 50
DEV_FRACTION = 1 / 3
FIELDS = (
    "image_id",
    "source",  # coco-train2017 | coco-val2017 | oi-<subset>
    "subset",  # download subset (COCO split or Open Images subset)
    "label",  # pos | neg
    "kind",  # boxed | image-level | verified-negative | lookalike:<class>
    "category",
    "boxes",  # JSON [[x1, y1, x2, y2], ...] - COCO in pixels, Open Images normalised
    "license",
    "author",
    "url",
)


# ---------------------------------------------------------------- COCO


def coco_rows(zip_path: Path, split: str, evaluation_only: bool = False) -> list[dict]:
    """Hydrant images under derivative-friendly licences, or (``evaluation_only``) the others:
    NC / ND images are only ever scored, never trained on."""
    with zipfile.ZipFile(zip_path) as z:
        d = json.loads(z.read(f"annotations/instances_{split}.json"))
    names = {lic["id"]: lic["url"] for lic in d["licenses"]}
    boxes = defaultdict(list)
    for a in d["annotations"]:
        if a["category_id"] == COCO_HYDRANT and not a["iscrowd"]:
            x, y, w, h = a["bbox"]
            boxes[a["image_id"]].append([x, y, x + w, y + h])
    rows = []
    for im in d["images"]:
        if im["id"] in boxes and (im["license"] in COCO_LICENCES) != evaluation_only:
            rows.append(
                {
                    "image_id": f"{im['id']:012d}",
                    "source": f"coco-{split}",
                    "subset": split,
                    "label": "pos",
                    "kind": "boxed",
                    "category": "hydrant",
                    "boxes": json.dumps([[round(v, 2) for v in b] for b in boxes[im["id"]]]),
                    "license": COCO_LICENCES.get(im["license"], names[im["license"]]),
                    "author": "",
                    "url": im["coco_url"],
                }
            )
    return sorted(rows, key=lambda r: r["image_id"])


# ---------------------------------------------------------------- Open Images


def _oi_ok(m: dict | None, coco_flickr: set[str]) -> bool:
    return (
        m is not None
        and m["Rotation"] in ("0", "0.0")
        and m["License"] == CC_BY
        and r0a.flickr_id(m["OriginalURL"]) not in coco_flickr
    )


def _oi_row(m: dict, subset: str, label: str, kind: str, category: str, boxes: list) -> dict:
    return {
        "image_id": m["ImageID"],
        "source": f"oi-{subset}",
        "subset": subset,
        "label": label,
        "kind": kind,
        "category": category,
        "boxes": json.dumps(boxes),
        "license": m["License"],
        "author": m["Author"],
        "url": m["OriginalLandingURL"] or m["OriginalURL"],
    }


def hydrant_ids(meta: Path) -> dict[str, set[str]]:
    """Every Open Images image with any hydrant label or box (kept out of the look-alikes)."""
    out: dict[str, set[str]] = {}
    files = {
        "train": ("train-imagelabels-hydrant.csv", "train-bbox-hydrant.csv"),
        "validation": (
            "validation-annotations-human-imagelabels-boxable.csv",
            "validation-annotations-bbox.csv",
        ),
        "test": ("test-annotations-human-imagelabels-boxable.csv", "test-annotations-bbox.csv"),
    }
    for subset, (lab, bbox) in files.items():
        ids = {r["ImageID"] for r in r0a.read_csv(meta / lab) if r["LabelName"] == r0a.HYDRANT}
        ids |= {r["ImageID"] for r in r0a.read_csv(meta / bbox) if r["LabelName"] == r0a.HYDRANT}
        out[subset] = ids
    return out


def free_boxed_positives(meta: Path, used: set[str], coco_flickr: set[str]) -> list[dict]:
    """Boxed hydrant images no earlier study used (test set)."""
    rows = []
    for subset, bbox, img in (
        ("train", "train-bbox-hydrant.csv", "train-images-hydrant.csv"),
        ("validation", "validation-annotations-bbox.csv", "validation-images-with-rotation.csv"),
        ("test", "test-annotations-bbox.csv", "test-images-with-rotation.csv"),
    ):
        bx = defaultdict(list)
        for r in r0a.read_csv(meta / bbox):
            if r["LabelName"] == r0a.HYDRANT:
                bx[r["ImageID"]].append(r0a.box_of(r))
        ids = set(bx) - used
        info = {r["ImageID"]: r for r in r0a.read_csv(meta / img) if r["ImageID"] in ids}
        for iid in sorted(ids):
            m = info.get(iid)
            if not _oi_ok(m, coco_flickr):
                continue
            st, _ = r0a.stratum(bx[iid])
            rows.append(_oi_row(m, subset, "pos", "boxed", st, [b["xyxy"] for b in bx[iid]]))
    return rows


def lookalike_rows(meta: Path, exclude: set[str], coco_flickr: set[str], seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    taken: set[str] = set()
    for subset in ("validation", "test"):
        by_class = defaultdict(set)
        for r in r0a.read_csv(meta / f"{subset}-annotations-bbox.csv"):
            if r["LabelName"] in LOOKALIKES and r["ImageID"] not in exclude:
                by_class[r["LabelName"]].add(r["ImageID"])
        cand = set().union(*by_class.values()) if by_class else set()
        info = {
            r["ImageID"]: r
            for r in r0a.read_csv(meta / f"{subset}-images-with-rotation.csv")
            if r["ImageID"] in cand
        }
        for cls in sorted(LOOKALIKES):
            ok = sorted(
                i for i in by_class[cls] if i not in taken and _oi_ok(info.get(i), coco_flickr)
            )
            k = min(LOOKALIKE_PER_CLASS // 2, len(ok))  # half from each subset
            for i in sorted(rng.choice(len(ok), size=k, replace=False)) if k else []:
                name, cat = LOOKALIKES[cls]
                rows.append(_oi_row(info[ok[i]], subset, "neg", f"lookalike:{name}", cat, []))
                taken.add(ok[i])
    return rows


# ---------------------------------------------------------------- splits


def dev_mask(n: int, seed: int) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    mask[np.random.default_rng(seed).choice(n, size=round(n * DEV_FRACTION), replace=False)] = True
    return mask


def build(meta: Path, coco_zip: Path, coco_flickr: set[str]) -> tuple[dict[str, list], dict]:
    v3dev = r0a.read_csv(Path("data/v3/realimg-dev.csv"))
    v3res = r0a.read_csv(Path("data/v3/realimg-reserve.csv"))
    used = (
        {r["image_id"] for r in r0a.read_csv(Path("data/r0a/manifest-formal.csv"))}
        | {r["image_id"] for r in r0a.read_csv(Path("data/r0a/manifest-dev.csv"))}
        | {r["image_id"] for r in v3dev}
        | {r["image_id"] for r in v3res}
    )
    hyd = set().union(*hydrant_ids(meta).values())
    # test: frozen before any training or detector run on it
    test = [
        {**_v3_row(r), "kind": "image-level" if r["label"] == "pos" else "verified-negative"}
        for r in v3res
    ] + free_boxed_positives(meta, used, coco_flickr)
    # all remaining boxed Open Images hydrants fail R0a's rules (rotation unknown / in COCO), so
    # the boxed test positives are the COCO val2017 images not in dev (evaluation only)
    test += coco_rows(coco_zip, "val2017", evaluation_only=True)
    # train / dev
    negs = [{**_v3_row(r), "kind": "verified-negative"} for r in v3dev if r["label"] == "neg"]
    looks = lookalike_rows(meta, hyd | used, coco_flickr, SEED)
    train, dev = coco_rows(coco_zip, "train2017"), coco_rows(coco_zip, "val2017")
    dev += [{**_v3_row(r), "kind": "image-level"} for r in v3dev if r["label"] == "pos"]
    for i, group in enumerate((negs, looks)):
        group = sorted(group, key=lambda r: r["image_id"])
        m = dev_mask(len(group), SEED + i)
        train += [r for r, d in zip(group, m, strict=True) if not d]
        dev += [r for r, d in zip(group, m, strict=True) if d]
    out = {"train": train, "dev": dev, "test": test}
    check_disjoint(out)
    audit = {
        k: {
            "n": len(v),
            "by_kind": dict(Counter(r["kind"] for r in v)),
            "by_label": dict(Counter(r["label"] for r in v)),
            "licenses": dict(Counter(r["license"] for r in v)),
        }
        for k, v in out.items()
    }
    return out, audit


def _v3_row(r: dict) -> dict:
    return {
        "image_id": r["image_id"],
        "source": f"oi-{r['subset']}",
        "subset": r["subset"],
        "label": r["label"],
        "category": r.get("stratum", ""),
        "boxes": r["boxes"],
        "license": r["license"],
        "author": r["author"],
        "url": r["original_url"],
    }


def check_disjoint(splits: dict[str, list[dict]]) -> None:
    seen: dict[str, str] = {}
    for name, rows in splits.items():
        for r in rows:
            key = f"{r['source']}:{r['image_id']}"
            if key in seen and seen[key] != name:
                raise ValueError(f"{key} in both {seen[key]} and {name}")
            seen[key] = name


def write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def image_path(images: Path, row: dict) -> Path:
    return images / row["source"] / f"{row['image_id']}.jpg"


def download(rows: list[dict], images: Path, workers: int = 8) -> dict:
    """Open Images from the public S3 mirror (as R0a), COCO from images.cocodataset.org."""
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image

    def one(row):
        p = image_path(images, row)
        if p.exists():
            return "cached"
        p.parent.mkdir(parents=True, exist_ok=True)
        local = r0a.image_path(R0A_IMAGES, row)  # the v3 development half is already here
        if not row["source"].startswith("coco") and local.exists():
            os.link(local, p)
            return "linked"
        if row["source"].startswith("coco"):
            url = f"http://images.cocodataset.org/{row['subset']}/{row['image_id']}.jpg"
        else:
            url = r0a.S3.format(subset=row["subset"], image_id=row["image_id"])
        err = ""
        for k in range(4):
            try:
                data = urllib.request.urlopen(url, timeout=120).read()
                tmp = p.with_suffix(".part")
                tmp.write_bytes(data)
                with Image.open(tmp) as im:
                    im.verify()
                tmp.rename(p)
                return "ok"
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(2 * (k + 1))
        return f"failed: {err}"

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, rows))
    return dict(Counter(v.split(":")[0] for v in res))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detv2.data")
    ap.add_argument("action", choices=["split", "download"])
    ap.add_argument("--meta", default="data/raw/r0a/meta")
    ap.add_argument("--coco-zip", default="data/raw/r0a/coco/annotations_trainval2017.zip")
    ap.add_argument("--coco-flickr", default="data/raw/r0a/coco/flickr_ids.txt")
    ap.add_argument("--out", default="data/detv2")
    ap.add_argument("--manifest")
    ap.add_argument("--images", default="data/raw/detv2")
    args = ap.parse_args(argv)
    if args.action == "download":
        if "test" in Path(args.manifest).name:
            raise SystemExit("test images are fetched only for the formal run (decision 027)")
        print(download(r0a.read_csv(Path(args.manifest)), Path(args.images)))
        return 0
    coco = {ln.strip() for ln in open(args.coco_flickr) if ln.strip()}
    splits, audit = build(Path(args.meta), Path(args.coco_zip), coco)
    out = Path(args.out)
    for name, rows in splits.items():
        write(rows, out / f"{name}.csv")
    (out / "split.json").write_text(json.dumps(audit, indent=1) + "\n")
    print(json.dumps(audit, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
