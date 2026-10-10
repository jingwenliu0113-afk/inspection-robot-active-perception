"""Grab one RGB and one depth frame from the inspector camera via gz-transport.

Run inside the container. STATUS: written before the image existed (M2 debugging expected).
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--rgb-topic", default="/inspector/rgb")
    ap.add_argument("--depth-topic", default="/inspector/depth")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    from gz.msgs10.image_pb2 import Image
    from gz.transport13 import Node

    got: dict[str, np.ndarray] = {}
    lock = threading.Lock()

    def make_cb(key: str, dtype, channels: int):
        def cb(msg: Image) -> None:
            arr = np.frombuffer(msg.data, dtype=dtype)
            arr = (
                arr.reshape(msg.height, msg.width, channels)
                if channels > 1
                else arr.reshape(msg.height, msg.width)
            )
            with lock:
                got.setdefault(key, arr.copy())

        return cb

    node = Node()
    node.subscribe(Image, args.rgb_topic, make_cb("rgb", np.uint8, 3))
    node.subscribe(Image, args.depth_topic, make_cb("depth", np.float32, 1))
    t0 = time.time()
    while time.time() - t0 < args.timeout:
        with lock:
            if "rgb" in got and "depth" in got:
                break
        time.sleep(0.05)
    out = Path(args.out)
    for key, arr in got.items():
        np.save(out / f"{args.label}_{key}.npy", arr)
        print(
            f"{args.label} {key}: shape={arr.shape} dtype={arr.dtype} mean={float(arr.mean()):.3f}"
        )
    missing = {"rgb", "depth"} - set(got)
    if missing:
        print(f"missing frames: {sorted(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
