"""v1 must stay bit-identical after v2 was added (decision 011 section 2).

Re-runs the frozen v1 configuration on core VAL (never the sealed test) and compares
with the stage-3 numbers recorded in results/tuning/stage3_val.json. Needs the core frame store
``renders/core`` (not in git: ``./docker/render.sh``, docs/reproduce.md §C; the VAL episodes are
enough); skipped where it is absent (e.g. a fresh clone). The detections are the committed GPU
output ``results/core/detector-v1.jsonl`` (identical to the local cache ``runs/core/``).
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERS = ROOT / "renders" / "core"
DETS = ROOT / "results" / "core" / "detector-v1.jsonl"

pytestmark = pytest.mark.skipif(
    not RENDERS.is_dir(), reason="needs renders/core (docs/reproduce.md §C)"
)


def test_v1_val_numbers_reproduce_exactly():
    from activeperception import frozen, tune
    from activeperception.types import Split

    specs, gts, world = tune.load(
        str(ROOT / "data/episodes/gazebo-core.json"), str(DETS), str(RENDERS), Split.VAL
    )
    got = tune.stage_val(specs, gts, world, frozen.DECISION_V1, frozen.RULE_NBV_V1)
    want = json.loads((ROOT / "results/tuning/stage3_val.json").read_text())
    assert got == want
