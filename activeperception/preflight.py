"""Pre-flight check before CPU / GPU / memory-heavy work on the shared Mac (MACHINE_POLICY).

Other projects may run heavy work without taking the Mac heavy lock (e.g. a local LLM server
holding the Apple GPU), so the lock alone is not enough. Before a long run:

    uv run python -m activeperception.preflight            # CPU / RAM / lock
    uv run python -m activeperception.preflight --gpu      # + the Apple GPU (MPS work)

Exit status 0 = quiet enough to start; 1 = do not start (the report says why). Thresholds are
conservative defaults for a 12-core Mac shared by several projects, not measured optima.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

from .v5.maclock import holder

MAX_LOAD_FRACTION = 0.5  # 1-min load average / logical CPUs
MIN_MEM_FREE_PCT = 25.0  # macOS memory_pressure "System-wide memory free percentage"
MAX_GPU_UTIL_PCT = 50.0  # IOAccelerator "Device Utilization %" (only checked with --gpu)


def parse_mem_free(text: str) -> float | None:
    m = re.search(r"memory free percentage:\s*([0-9.]+)%", text)
    return float(m.group(1)) if m else None


def parse_gpu_util(text: str) -> float | None:
    vals = [float(v) for v in re.findall(r'"Device Utilization %"=([0-9.]+)', text)]
    return max(vals) if vals else None


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def top_processes(n: int = 5) -> list[str]:
    out = _run(["ps", "-Ao", "%cpu,%mem,comm", "-r"]).splitlines()[1 : n + 1]
    return [" ".join(line.split()) for line in out]


IOREG = ["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"]


def snapshot() -> dict:
    return {
        "load1": os.getloadavg()[0],
        "ncpu": os.cpu_count() or 1,
        "mem_free_pct": parse_mem_free(_run(["memory_pressure"])),
        "gpu_util_pct": parse_gpu_util(_run(IOREG)),
        "lock": holder(),
        "top": top_processes(),
    }


def problems(snap: dict, gpu: bool = False) -> list[str]:
    out = []
    if snap["lock"] is not None:
        out.append(f"Mac heavy lock held: {snap['lock']}")
    if snap["load1"] / snap["ncpu"] > MAX_LOAD_FRACTION:
        out.append(f"CPU busy: load {snap['load1']:.1f} on {snap['ncpu']} CPUs")
    if snap["mem_free_pct"] is not None and snap["mem_free_pct"] < MIN_MEM_FREE_PCT:
        out.append(f"memory low: {snap['mem_free_pct']:.0f}% free")
    if gpu and snap["gpu_util_pct"] is not None and snap["gpu_util_pct"] > MAX_GPU_UTIL_PCT:
        out.append(f"Apple GPU busy: {snap['gpu_util_pct']:.0f}% utilisation")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.preflight")
    ap.add_argument("--gpu", action="store_true", help="the job uses the Apple GPU (MPS)")
    args = ap.parse_args(argv)
    snap = snapshot()
    mem = "?" if snap["mem_free_pct"] is None else f"{snap['mem_free_pct']:.0f}%"
    gpu = "?" if snap["gpu_util_pct"] is None else f"{snap['gpu_util_pct']:.0f}%"
    print(
        f"load {snap['load1']:.1f} / {snap['ncpu']} CPUs | memory free {mem} | Apple GPU {gpu} | "
        f"lock {'held' if snap['lock'] else 'free'}"
    )
    for line in snap["top"]:
        print(f"  {line}")
    bad = problems(snap, args.gpu)
    for p in bad:
        print(f"NOT STARTING: {p}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
