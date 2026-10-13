"""Render every viewpoint of every episode once (decision 007). Runs INSIDE the container.

For each episode: write the full-scene SDF, start a headless ``gz sim`` server, and for
the initial viewpoint + all candidates teleport and grab RGB / depth / labels. When the
object is present, park the pillars out of view over gz-transport and grab the labels again (the
clear GT pass). Output format: ``activeperception.framestore`` (``render-v1``).

Sensors run at 30 Hz by default: frames are pixel-identical to 10 Hz renders (checked
2026-10-13 on pilot-g0000-v0/v1), at about half the wall time.

Shard with ``--worker k --workers n`` and run n containers in parallel.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

import numpy as np

from ..framestore import encode_depth_mm, write_episode_frames
from ..serialize import load_spec_set, spec_digest
from ..types import EpisodeSpec
from .gz_client import GzClient
from .sdf import LABEL_PILLAR, PILLAR_PREFIX, SDF_VERSION, world_sdf


class GzServer:
    """A headless gz sim server process for one world file."""

    def __init__(self, sdf_path: Path, log_path: Path, verbosity: int = 1):
        self._log = open(log_path, "w")  # noqa: SIM115 - closed in stop()
        self.proc = subprocess.Popen(
            ["gz", "sim", "-s", "-r", "--headless-rendering", "-v", str(verbosity), str(sdf_path)],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self, timeout: float = 15.0) -> None:
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
        self._log.close()


def _grab_pass(client: GzClient, spec: EpisodeSpec, settle_ns: int):
    vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
    out = {"rgb": [], "depth_mm": [], "labels": [], "stamps_ns": [], "t_ref_ns": []}
    for vp in vps:
        t_ref, frames = client.teleport_and_grab(vp.pose, settle_ns=settle_ns)
        labels = frames["labels"].array
        if labels.ndim == 3:
            if not (labels == labels[..., :1]).all():
                raise RuntimeError("semantic label channels differ")
            labels = labels[..., 0]
        out["rgb"].append(frames["rgb"].array)
        out["depth_mm"].append(encode_depth_mm(frames["depth"].array))
        out["labels"].append(labels)
        out["stamps_ns"].append(min(f.stamp_ns for f in frames.values()))
        out["t_ref_ns"].append(t_ref)
    return {k: np.stack(v) for k, v in out.items()}


def render_episode(
    spec: EpisodeSpec,
    out_dir: Path,
    work_dir: Path,
    client: GzClient,
    update_rate: float,
    settle_periods: float,
) -> dict:
    t0 = time.monotonic()
    settle_ns = int(settle_periods * 1e9 / update_rate)
    sdf_path = work_dir / f"{spec.episode_id}.sdf"
    sdf_path.write_text(world_sdf(spec, update_rate=update_rate))
    server = GzServer(sdf_path, work_dir / f"{spec.episode_id}.log")
    try:
        client.reset()
        client.wait_ready(120)
        full = _grab_pass(client, spec, settle_ns)
        clear = None
        if spec.layout.object_present:
            client.park_models([f"{PILLAR_PREFIX}{i}" for i in range(len(spec.layout.occluders))])
            clear = _grab_pass(client, spec, settle_ns)
            if (clear["labels"] == LABEL_PILLAR).any():
                raise RuntimeError("clear pass still shows pillar labels")
    finally:
        server.stop()
    vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
    meta = {
        "episode_id": spec.episode_id,
        "spec_digest": spec_digest(spec),
        "generator_version": spec.generator_version,
        "sdf_version": SDF_VERSION,
        "image_id": os.environ.get("AP_IMAGE_ID", "unknown"),
        "update_rate": update_rate,
        "settle_ns": settle_ns,
        "depth_kind": "planar",
        "seconds": round(time.monotonic() - t0, 2),
    }
    arrays = {
        "vp_ids": np.array([vp.id for vp in vps], dtype=np.int16),
        "poses": np.array(
            [[vp.pose.x, vp.pose.y, vp.pose.z, vp.pose.yaw, vp.pose.pitch] for vp in vps]
        ),
        **full,
    }
    if clear is not None:
        arrays["labels_clear"] = clear["labels"]
        arrays["stamps_clear_ns"] = clear["stamps_ns"]
        arrays["t_ref_clear_ns"] = clear["t_ref_ns"]
    write_episode_frames(out_dir / f"{spec.episode_id}.npz", arrays, meta)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.sim.render")
    ap.add_argument("--specs", required=True, help="spec-set JSON written on the host")
    ap.add_argument("--out", required=True, help="frame store directory")
    ap.add_argument("--episodes", help="comma-separated episode ids (default: all)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--update-rate", type=float, default=30.0)
    ap.add_argument("--settle-periods", type=float, default=2.5)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    specs, _ = load_spec_set(args.specs)
    if args.episodes:
        wanted = set(args.episodes.split(","))
        specs = [s for s in specs if s.episode_id in wanted]
    out_dir = Path(args.out)
    if not args.overwrite:  # skip finished episodes before sharding so resumes stay balanced
        specs = [s for s in specs if not (out_dir / f"{s.episode_id}.npz").exists()]
    specs = specs[args.worker :: args.workers]
    if args.limit:
        specs = specs[: args.limit]
    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    client = GzClient()
    done = 0
    for spec in specs:
        for attempt in range(3):  # transient gz-transport discovery stalls under load
            try:
                meta = render_episode(
                    spec, out_dir, work_dir, client, args.update_rate, args.settle_periods
                )
                break
            except Exception as exc:  # noqa: BLE001 - logged and retried with a fresh server
                print(f"[w{args.worker}] {spec.episode_id} attempt {attempt + 1}: {exc!r}")
                if attempt == 2:
                    raise
        done += 1
        print(f"[w{args.worker}] {spec.episode_id} {meta['seconds']}s", flush=True)
    print(f"[w{args.worker}] rendered {done} episodes into {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
