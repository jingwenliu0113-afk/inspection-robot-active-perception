"""H-P development evaluation (decision 037 appendix A): B0 = frozen v5, HP-1.2 (main), HP-1.3
(sensitivity), B-floor and the Oracle-pose ceiling, full harness, development data only.

    uv run python -m activeperception.preflight || exit 1
    uv run python -m activeperception.v6.dev --out runs/hp-dev --workers 5

Every arm replays all four methods at budgets 1-5 with the same seeds (Rule re-selects its views
on each arm's observations). Writes ``<out>/<namespace>/<condition>-<arm>.json``; existing files
are kept (the run can be resumed). Each job waits while another project holds the Mac heavy lock.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..v3.eval import DEV_NAMESPACES
from ..v4.devreport import row, summarize
from ..v5 import frozen_v5
from ..v5.formal import run_when_free
from .configs import ARMS

NAMESPACES = ("v3-dev", "v3-dev-dx")
CONDITIONS = ("D3xP0", "D1xL2:L1", "D0xP0", "D1xL1", "D2xL2", "D3xL1")  # D3xP0 first
ONLY = {  # arm -> conditions (others: all); appendix A.2
    "Bfloor": ("D0xP0", "D3xP0"),  # L1 / L2 already report >= the raised floor: identical to B0
    "Oracle": ("D3xP0", "D3xL1"),
}


def file_name(cond: str, arm: str) -> str:
    return f"{cond.replace(':', '_')}-{arm}.json"


def jobs(namespaces=NAMESPACES, conditions=CONDITIONS, arms=tuple(ARMS)) -> list[tuple]:
    out = []
    for cond in conditions:
        depth, rest = cond.split("x")
        pose, prior = (rest.split(":") + [None])[:2]
        for ns in namespaces:
            for arm in arms:
                if arm in ONLY and cond not in ONLY[arm]:
                    continue
                cfg = ARMS[arm]
                out.append(
                    (ns, cond, arm, (ns, depth, pose, cfg, True, frozen_v5.TIE_BREAK, prior))
                )
    return out


def _run(job: tuple) -> dict:
    return run_when_free(job)


def main(argv: list[str] | None = None) -> int:
    from ..preflight import problems, snapshot

    ap = argparse.ArgumentParser(prog="activeperception.v6.dev")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--namespaces", default=",".join(NAMESPACES))
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args(argv)
    namespaces = args.namespaces.split(",")
    for ns in namespaces:
        if ns not in DEV_NAMESPACES:
            raise SystemExit(f"{ns}: not development data")
    bad = problems(snapshot())
    if bad:
        raise SystemExit("not starting: " + "; ".join(bad))
    todo = []
    for ns, cond, arm, job in jobs(namespaces, args.conditions.split(","), args.arms.split(",")):
        path = Path(args.out) / ns / file_name(cond, arm)
        if path.exists():
            print(f"{path} exists, skip", flush=True)
            continue
        todo.append((path, job))
    print(f"{len(todo)} jobs, {args.workers} workers", flush=True)
    with ProcessPoolExecutor(min(args.workers, max(len(todo), 1))) as ex:
        for (path, _), r in zip(todo, ex.map(_run, [j for _, j in todo]), strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(r) + "\n")
            tmp.rename(path)
            print(row(f"{path.parent.name}/{path.stem}", summarize(r)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
