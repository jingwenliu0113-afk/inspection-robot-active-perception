"""Formal test runner (decision 009) on ray-cast proxy frames, and frozen-config provenance."""

import json
from pathlib import Path

import numpy as np
import pytest

from activeperception import experiment, frozen
from activeperception.detector.cache import DetectionCache
from activeperception.episodes import build_episode_set
from activeperception.framestore import FrameStore
from activeperception.sensing import gt_visibility_from_labels
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import write_proxy_frames
from activeperception.sim.replay import GazeboReplayWorld
from activeperception.sim.sdf import LABEL_OBJECT


def test_frozen_config_matches_tuning_results():
    root = Path(__file__).resolve().parents[1] / "results" / "tuning"
    s1 = json.loads((root / "stage1_decision.json").read_text())["best"]["params"]
    s2 = json.loads((root / "stage2_rule.json").read_text())["best"]["params"]
    assert {k: getattr(frozen.DECISION_V1, k) for k in s1} == s1
    assert {k: getattr(frozen.RULE_NBV_V1, k) for k in s2} == pytest.approx(s2)
    assert frozen.FORMAL_BUDGETS == (1, 2, 3, 5)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    specs = build_episode_set("exp", 3)
    root = tmp_path_factory.mktemp("exp-frames")
    for s in specs:
        write_proxy_frames(s, root, SyntheticWorld().params.proxy_radius)
    store = FrameStore(root)
    cache = DetectionCache("label-test")
    for s in specs:
        fr = store.episode(s.episode_id)
        for vid in fr.viewpoint_ids:
            clear = fr.labels_clear(vid)
            dets = []
            if clear is not None:
                lv = gt_visibility_from_labels(fr.labels(vid), clear, LABEL_OBJECT)
                if lv.bbox_visible is not None:
                    dets.append([0.97 if lv.vis_fraction > 0.3 else 0.2, *lv.bbox_visible])
            cache.put(s.episode_id, vid, dets)
    world = GazeboReplayWorld(store, cache)
    gts = {s.episode_id: world.ground_truth(s) for s in specs}
    return specs, gts, world, experiment.run_all(specs, gts, world, (1, 2, 3))


def test_run_all_shapes_and_budget_one(runs):
    specs, _, _, r = runs
    assert len(r.outcomes["random"][2]) == len(frozen.RANDOM_SEEDS)
    assert all(len(seed) == len(specs) for seed in r.outcomes["rule"][3])
    idx = np.arange(len(specs))
    accs = {m: r.stat(m, 1, "accuracy", idx) for m in experiment.METHODS}
    assert len(set(accs.values())) == 1  # budget 1 = single view for every method


def test_summary_diffs_and_gate(runs):
    specs, gts, world, r = runs
    summ = experiment.summarize(r, (1, 2, 3), n_boot=20, boot_budgets=(2, 3))
    assert summ["rule@2"]["accuracy_ci95"] is not None
    diffs = experiment.paired_differences(r, (1, 2, 3, 5)[:3], n_boot=20)
    d = diffs["rule-random@1:accuracy"]
    assert d["diff"] == 0.0 and d["ci95"] == [0.0, 0.0]
    fails = experiment.residual_failures(r, gts, budgets=(2,))
    assert all(f["budget"] == 2 for f in fails)
    det = experiment.detector_vs_success(specs, world, 0.7)
    assert det["present_frames"] == 13 * sum(s.layout.object_present for s in specs)


def test_cli_refuses_existing_output(tmp_path):
    with pytest.raises(SystemExit):
        experiment.main(
            ["test", "--episodes", "x.json", "--detections", "y", "--out", str(tmp_path)]
        )
