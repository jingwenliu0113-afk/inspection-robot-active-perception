"""M2 smoke test, run INSIDE the container against a running ``gz sim`` server.

Checks (decision 007 / SPEC §9): sensor formats, teleport changes the view, every frame
is newer than the teleport reference, and re-rendering the same pose is pixel-identical.
Writes a JSON report and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..episodes import generate_episode
from .gz_client import GzClient


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.sim.gz_smoke")
    ap.add_argument("--namespace", default="pilot")
    ap.add_argument("--group", type=int, default=0)
    ap.add_argument("--variant", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    spec = generate_episode(args.namespace, args.group, args.variant)
    client = GzClient()
    t0 = time.monotonic()
    client.wait_ready(120)
    report: dict = {"episode": spec.episode_id, "ready_s": round(time.monotonic() - t0, 2)}
    order = [spec.initial_viewpoint, *spec.candidate_viewpoints[::3], spec.candidate_viewpoints[0]]
    shots = []
    for vp in order:
        t1 = time.monotonic()
        t_ref, frames = client.teleport_and_grab(vp.pose)
        shots.append((vp.id, t_ref, frames, time.monotonic() - t1))
    checks = {}
    first = shots[0][2]
    checks["formats"] = (
        first["rgb"].array.shape == (spec.camera.height, spec.camera.width, 3)
        and first["rgb"].array.dtype == np.uint8
        and first["depth"].array.dtype == np.float32
        and first["labels"].array.shape[:2] == (spec.camera.height, spec.camera.width)
    )
    checks["fresh_after_teleport"] = all(
        f.stamp_ns > t_ref for _, t_ref, frames, _ in shots for f in frames.values()
    )
    checks["teleport_changes_view"] = not np.array_equal(
        shots[1][2]["rgb"].array, shots[2][2]["rgb"].array
    )
    a, b = shots[1][2], shots[-1][2]  # candidate 0, visited twice
    checks["same_pose_identical"] = all(
        np.array_equal(a[k].array, b[k].array, equal_nan=a[k].array.dtype.kind == "f")
        for k in ("rgb", "depth", "labels")
    )
    labels = first["labels"].array
    depth0 = first["depth"].array
    report.update(
        {
            "checks": checks,
            "per_view_s": [round(s[3], 3) for s in shots],
            "stamps_s": [round(s[2]["rgb"].stamp_ns / 1e9, 3) for s in shots],
            "label_values": sorted(int(v) for v in np.unique(labels)),
            "labels_channels_equal": bool(labels.ndim == 2 or (labels == labels[..., :1]).all()),
            "depth_nonfinite_values": sorted(
                {str(v) for v in np.unique(depth0[~np.isfinite(depth0)])}
            ),
        }
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
