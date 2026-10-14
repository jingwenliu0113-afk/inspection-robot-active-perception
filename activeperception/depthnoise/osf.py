"""Download the plane recordings of Rustler et al. 2025 (OSF f2seb, CC BY 4.0) for decision 028.

    uv run python -m activeperception.depthnoise.osf --out data/raw/depthnoise --cameras D435,D455

"Empirical Comparison of Four Stereoscopic Depth Sensing Cameras for Robotics Applications"
(https://arxiv.org/abs/2501.07421, data https://osf.io/f2seb/). A textured plane at 13 laser-
measured distances (60-400 cm), 30 depth frames per camera and distance, default settings.
Only the depth PNGs of the requested cameras and the intrinsics are fetched (no RGB, no
point clouds); the files stay in ``data/raw/`` (not committed), a manifest with sizes and sha256
goes next to them. Attribution is required (CC BY 4.0).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.osf.io/v2/nodes/f2seb/files/osfstorage/"
PLANES = "6785272f41ccc035b7342116/"
INTRINSICS = "69c3a72201eb241cc354d1ae/"


def _get(url: str) -> dict:
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"OSF listing failed: {url}")


def listing(url: str) -> list[dict]:
    out = []
    while url:
        d = _get(url)
        out += d["data"]
        url = d["links"].get("next")
    return out


def walk(url: str, prefix: str = ""):
    """(relative path, download URL, size) of every file below ``url``."""
    for x in listing(url):
        a = x["attributes"]
        path = f"{prefix}{a['name']}"
        if a["kind"] == "folder":
            yield from walk(x["relationships"]["files"]["links"]["related"]["href"], path + "/")
        else:
            yield path, x["links"]["download"], a["size"]


def wanted(path: str, cameras: tuple[str, ...]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".png") and "depth" in name and any(f"_{c}_" in name for c in cameras)


def fetch(items: list[tuple[str, str, int]], out: Path, workers: int = 6) -> list[dict]:
    def one(item):
        path, url, size = item
        p = out / path
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            for k in range(5):
                try:
                    data = urllib.request.urlopen(url, timeout=120).read()
                    tmp = p.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.rename(p)
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 * (k + 1))
        ok = p.exists() and p.stat().st_size == size
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if ok else ""
        return {"path": path, "size": size, "ok": ok, "sha256": sha}

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, items))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.depthnoise.osf")
    ap.add_argument("--out", default="data/raw/depthnoise")
    ap.add_argument("--cameras", default="D435,D455")
    ap.add_argument("--max-mb", type=float, default=900.0)
    args = ap.parse_args(argv)
    cams = tuple(args.cameras.split(","))
    out = Path(args.out)
    items = [i for i in walk(API + PLANES, "planes/") if wanted(i[0], cams)]
    items += list(walk(API + INTRINSICS, "intrinsics/"))
    total = sum(s for _, _, s in items) / 1e6
    print(f"{len(items)} files, {total:.0f} MB")
    if total > args.max_mb:
        raise SystemExit(f"{total:.0f} MB > {args.max_mb} MB: refusing (large download)")
    res = fetch(items, out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "Rustler et al. 2025, OSF f2seb (CC BY 4.0), https://osf.io/f2seb/",
        "paper": "https://arxiv.org/abs/2501.07421",
        "files": res,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(sum(r["ok"] for r in res), "ok of", len(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
