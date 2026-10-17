"""Run one detector candidate over every frame of a frame store (decision 005 / 007).

    python -m activeperception.detector.run --frames renders/detsel --detector frcnn-mnv3 \\
        --device cuda --out runs/detsel/frcnn-mnv3.jsonl

Writes a ``DetectionCache`` (target class, low threshold) whose header records the model,
weights hash, package versions, device, and a batch-1 latency / memory benchmark
(warm-up first). Heavy GPU runs must be wrapped in the shared GPU lock (MACHINE_POLICY).
"""

from __future__ import annotations

import argparse
import platform
import resource
import sys
import time

import numpy as np

from ..framestore import FrameStore
from .cache import DetectionCache
from .models import CANDIDATES, load_detector, synchronize


def _peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def benchmark(det, images: list[np.ndarray], warmup: int, repeats: int) -> dict:
    import torch

    for img in images[:warmup]:
        det.detect(img)
    synchronize(det.device)
    if det.device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    times = []
    for i in range(repeats):
        img = images[i % len(images)]
        synchronize(det.device)
        t0 = time.perf_counter()
        det.detect(img)
        synchronize(det.device)
        times.append((time.perf_counter() - t0) * 1000.0)
    out = {
        "batch": 1,
        "warmup": warmup,
        "repeats": repeats,
        "latency_ms_p50": float(np.percentile(times, 50)),
        "latency_ms_p90": float(np.percentile(times, 90)),
        "latency_ms_mean": float(np.mean(times)),
        "peak_rss_mb": _peak_rss_mb(),
    }
    if det.device.startswith("cuda"):
        out["peak_vram_mb"] = torch.cuda.max_memory_allocated() / (1024 * 1024)
        out["gpu_name"] = torch.cuda.get_device_name(0)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detector.run")
    ap.add_argument("--frames", required=True, help="frame store directory")
    ap.add_argument("--detector", required=True, choices=sorted(CANDIDATES))
    ap.add_argument("--weights-dir", default="models")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--bench-warmup", type=int, default=20)
    ap.add_argument("--bench-repeats", type=int, default=200)
    ap.add_argument("--bench-only", action="store_true", help="skip the full pass")
    ap.add_argument("--limit", type=int, help="first N episodes only (smoke runs)")
    args = ap.parse_args(argv)

    import torch
    import torchvision

    store = FrameStore(args.frames)
    det = load_detector(args.detector, args.weights_dir, args.device)
    episodes = store.episode_ids()[: args.limit] if args.limit else store.episode_ids()
    bench_imgs = [store.episode(e).rgb(v) for e in episodes[:4] for v in (-1, 0, 4, 8)]
    bench = benchmark(det, bench_imgs, args.bench_warmup, args.bench_repeats)
    cand = CANDIDATES[args.detector]
    versions = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
    }
    meta = {
        "candidate": cand.name,
        "family": cand.family,
        "weights": cand.weights,
        "weights_sha256": cand.sha256,
        "license": cand.license,
        "n_params": det.n_params(),
        "device": det.device,
        "host": platform.platform(),
        "versions": versions,
        "frames": str(args.frames),
        "benchmark": bench,
    }
    cache = DetectionCache(args.detector, meta)
    if not args.bench_only:
        t0 = time.perf_counter()
        n = 0
        for eid in episodes:
            fr = store.episode(eid)
            for vid in fr.viewpoint_ids:
                cache.put(eid, vid, det.detect(fr.rgb(vid)))
                n += 1
        cache.meta["full_pass"] = {"frames": n, "seconds": round(time.perf_counter() - t0, 1)}
    cache.save(args.out)
    print(
        f"{args.detector} on {det.device}: p50 {bench['latency_ms_p50']:.1f} ms, "
        f"{len(cache.keys())} frames -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
