"""E1 data spec and validator (decision 036 §3; E1 itself is NOT started).

If E1 is approved, the user provides a folder of photos and ``manifest.csv`` with one row per
photo. Images stay local (``data/raw/e1/``, git-ignored); only the manifest without personal data
would be committed.

Columns: object_id, category, file, azimuth_deg, distance_m, camera_height_m, notes

- one object = one physical item, photographed on a ring around it (about every 45 deg);
- azimuth_deg: approximate bearing of the camera around the object (0-360, any origin);
- distance_m / camera_height_m: approximate (about 2 m and 1.1 m, like the inspection mast).

The dev / test split is by object and is decided here by a stable hash of object_id, so the
person taking the photos cannot influence it.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

FIELDS = ("object_id", "category", "file", "azimuth_deg", "distance_m", "camera_height_m", "notes")
CATEGORIES = {
    "hydrant": "target",
    "valve-pipe": "pipe-hardware",  # valves, standpipes, risers, hand pumps, pipe fittings
    "bollard-post": "street-furniture",
    "bin": "street-furniture",
    "mailbox": "street-furniture",
    "other": "other",
}
MIN_VIEWS = 8
MAX_GAP_DEG = 60.0
DISTANCE_M = (1.0, 3.5)
HEIGHT_M = (0.5, 1.8)
MIN_OBJECTS = {"target": 8, "pipe-hardware": 8, "street-furniture": 8}
TEST_SHARE = 0.5


def split_of(object_id: str) -> str:
    h = int.from_bytes(hashlib.sha256(f"e1|{object_id}".encode()).digest()[:4], "big")
    return "test" if (h % 1000) / 1000 < TEST_SHARE else "dev"


def read(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def validate(rows: list[dict], images: Path | None = None) -> list[str]:
    """Problems that block E1 (empty list = usable)."""
    bad = []
    if rows and set(FIELDS) - set(rows[0]):
        return [f"missing columns: {sorted(set(FIELDS) - set(rows[0]))}"]
    by_obj: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for i, r in enumerate(rows, 2):
        if r["category"] not in CATEGORIES:
            bad.append(f"row {i}: unknown category {r['category']!r}")
        key = (r["object_id"], r["file"])
        if key in seen:
            bad.append(f"row {i}: duplicate {key}")
        seen.add(key)
        try:
            az, d, h = float(r["azimuth_deg"]), float(r["distance_m"]), float(r["camera_height_m"])
        except ValueError:
            bad.append(f"row {i}: azimuth / distance / height must be numbers")
            continue
        if not 0 <= az < 360:
            bad.append(f"row {i}: azimuth {az} outside [0, 360)")
        if not DISTANCE_M[0] <= d <= DISTANCE_M[1]:
            bad.append(f"row {i}: distance {d} m outside {DISTANCE_M}")
        if not HEIGHT_M[0] <= h <= HEIGHT_M[1]:
            bad.append(f"row {i}: camera height {h} m outside {HEIGHT_M}")
        if images is not None and not (images / r["file"]).exists():
            bad.append(f"row {i}: file {r['file']} not found")
        by_obj[r["object_id"]].append(r)
    groups: dict[str, int] = defaultdict(int)
    for obj, rs in by_obj.items():
        cats = {r["category"] for r in rs}
        if len(cats) != 1:
            bad.append(f"{obj}: several categories {sorted(cats)}")
            continue
        groups[CATEGORIES[cats.pop()]] += 1
        if len(rs) < MIN_VIEWS:
            bad.append(f"{obj}: {len(rs)} views (< {MIN_VIEWS})")
        az = sorted(float(r["azimuth_deg"]) for r in rs if _num(r["azimuth_deg"]))
        if az:
            gaps = [b - a for a, b in zip(az, az[1:], strict=False)] + [360 - az[-1] + az[0]]
            if max(gaps) > MAX_GAP_DEG:
                bad.append(f"{obj}: azimuth gap {max(gaps):.0f} deg (> {MAX_GAP_DEG:.0f})")
    for g, n in MIN_OBJECTS.items():
        if groups[g] < n:
            bad.append(f"{g}: {groups[g]} objects (< {n})")
    return bad


def _num(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


def summary(rows: list[dict]) -> dict:
    objs: dict[str, dict] = {}
    for r in rows:
        o = objs.setdefault(r["object_id"], {"category": r["category"], "views": 0})
        o["views"] += 1
    by_split: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for oid, o in objs.items():
        by_split[split_of(oid)][CATEGORIES.get(o["category"], "?")] += 1
    return {
        "objects": len(objs),
        "photos": len(rows),
        "by_split": {k: dict(v) for k, v in by_split.items()},
    }


NAME_PATTERN = "<object_id>__<category>__<azimuth_deg>.jpg"  # e.g. valve03__valve-pipe__90.jpg


def manifest_from_names(files: list[str], distance_m=2.0, camera_height_m=1.1) -> list[dict]:
    """Manifest rows from file names following ``NAME_PATTERN`` (approximate distance and height
    default to the inspection geometry). Names that do not match are reported by ``validate``."""
    rows = []
    for f in sorted(files):
        stem = Path(f).stem
        parts = stem.split("__")
        oid, cat, az = (parts + ["", "", ""])[:3] if len(parts) != 3 else parts
        rows.append({
            "object_id": oid, "category": cat, "file": Path(f).name, "azimuth_deg": az,
            "distance_m": str(distance_m), "camera_height_m": str(camera_height_m), "notes": "",
        })  # fmt: skip
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="activeperception.inzone.e1spec")
    ap.add_argument("--manifest", help="manifest.csv; omit to build it from --images file names")
    ap.add_argument("--images")
    args = ap.parse_args(argv)
    if args.manifest:
        rows = read(Path(args.manifest))
    elif args.images:
        imgs = Path(args.images)
        rows = manifest_from_names(
            [p.name for p in imgs.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        )
    else:
        raise SystemExit("--manifest or --images is required")
    bad = validate(rows, Path(args.images) if args.images else None)
    print(json.dumps(summary(rows), indent=1))
    for b in bad:
        print("PROBLEM:", b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
