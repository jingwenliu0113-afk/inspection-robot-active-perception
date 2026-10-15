"""v5 development comparison (decision 033): each v5 band next to frozen v4 on the same data and
the same error draws, with paired Rule counts (episodes only one of the two gets right).

    uv run python -m activeperception.v5.devreport runs/v5-dev/band

Frozen v4 baselines on ``v3-dev`` are the existing v4 development runs (``runs/v4-dev``): v4 is
w4hjg8; on v3-dev (no distractor) w4hj is identical in every reported metric (decision 031 §1).
Development numbers only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..v3.formal import correct
from ..v4.devreport import HEADER, row, summarize

V4_BASELINE = {  # condition -> frozen v4 (or identical) development run on v3-dev
    "D0xP0": "runs/v4-dev/confirm/D0xP0-w4hj-g1-t0.json",
    "D1xL1": "runs/v4-dev/gate/D1xL1-w4hjg8-g1-t0.json",
    "D2xL2": "runs/v4-dev/gate/D2xL2-w4hjg8-g1-t0.json",
    "D3xL1": "runs/v4-dev/gate/D3xL1-w4hjg8-g1-t0.json",
    "D3xP0": "runs/v4-dev/confirm/D3xP0-w4hj-g1-t0.json",
    "D1xL2_L1": "runs/v4-dev/confirm/D1xL2-w4hj-g1-t0-prL1.json",
}


V4_BASELINE_DX = {  # the same on v3-dev-dx (distractors outside the zone)
    "D0xP0": "runs/v4-dev/gate-dx/D0xP0-w4hjg8-g1-t0.json",
    "D1xL1": "runs/v4-dev/gate-dx/D1xL1-w4hjg8-g1-t0.json",
    "D3xL1": "runs/v4-dev/gate-dx/D3xL1-w4hjg8-g1-t0.json",
}


def paired(a: dict, b: dict) -> str:
    """'a-only / b-only' correct episodes per budget 2 / 3 / 5."""
    ea, eb = a["rule_per_episode"], b["rule_per_episode"]
    cells = []
    for bud in (2, 3, 5):
        ao = sum(correct(ea[e], bud) and not correct(eb[e], bud) for e in ea)
        bo = sum(correct(eb[e], bud) and not correct(ea[e], bud) for e in ea)
        cells.append(f"+{ao}/−{bo}")
    return " ".join(cells)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    baselines = V4_BASELINE
    if "--dx" in argv:  # the runs were on v3-dev-dx
        argv.remove("--dx")
        baselines = V4_BASELINE_DX
    paths = [Path(p) for p in argv]
    files = sorted(f for p in paths for f in (p.glob("*.json") if p.is_dir() else [p]))
    by_cond: dict[str, list[Path]] = {}
    for f in files:
        cond = f.stem.rsplit("-", 1)[0]
        by_cond.setdefault(cond, []).append(f)
    head, sep = HEADER.splitlines()
    print(head + " 對 v4：只有 v5 對 / 只有 v4 對（b2 b3 b5） |")
    print(sep + "---|")
    for cond, fs in sorted(by_cond.items()):
        base = None
        if cond in baselines and Path(baselines[cond]).exists():
            base = json.loads(Path(baselines[cond]).read_text())
            print(row(f"{cond} v4", summarize(base)) + " — |")
        for f in fs:
            r = json.loads(f.read_text())
            hyp = r.get("v5", {}).get("hyp_scales", [])
            label = f"{f.stem} [{hyp[0]:.3f}–{hyp[-1]:.3f}]" if hyp else f.stem
            cmp_ = paired(r, base) if base is not None else "—"
            print(row(label, summarize(r)) + f" {cmp_} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
