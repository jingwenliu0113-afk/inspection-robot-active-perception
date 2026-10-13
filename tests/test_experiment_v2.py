"""Holdout v1-vs-v2 runner (decision 011 section 7) end to end on ray-cast proxy frames."""

import json

import pytest

from activeperception import experiment_v2
from activeperception.detector.cache import DetectionCache
from activeperception.episodes import HOLDOUT_NAMESPACE, build_episode_set
from activeperception.framestore import FrameStore
from activeperception.sensing import gt_visibility_from_labels
from activeperception.serialize import save_episode_set
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import write_proxy_frames
from activeperception.sim.replay import GazeboReplayWorld
from activeperception.sim.sdf import LABEL_OBJECT


@pytest.fixture(scope="module")
def holdout_files(tmp_path_factory):
    root = tmp_path_factory.mktemp("ho")
    specs = build_episode_set(HOLDOUT_NAMESPACE, 3)
    frames = root / "frames"
    for s in specs:
        write_proxy_frames(s, frames, SyntheticWorld().params.proxy_radius)
    store = FrameStore(frames)
    cache = DetectionCache("label-test")
    for s in specs:
        fr = store.episode(s.episode_id)
        for vid in fr.viewpoint_ids:
            clear = fr.labels_clear(vid)
            dets = []
            if clear is not None:
                lv = gt_visibility_from_labels(fr.labels(vid), clear, LABEL_OBJECT)
                if lv.bbox_visible is not None:
                    dets.append([0.97 if lv.vis_fraction > 0.3 else 0.1, *lv.bbox_visible])
            cache.put(s.episode_id, vid, dets)
    cache.save(root / "dets.jsonl")
    world = GazeboReplayWorld(store, cache)
    gts = {s.episode_id: world.ground_truth(s) for s in specs}
    save_episode_set(root / "eps.json", specs, gts, "gazebo", extra={"renders": str(frames)})
    return root


def test_holdout_report_structure(holdout_files):
    out = holdout_files / "report"
    args = [
        "holdout",
        "--episodes",
        str(holdout_files / "eps.json"),
        "--detections",
        str(holdout_files / "dets.jsonl"),
        "--out",
        str(out),
        "--n-boot",
        "10",
    ]
    assert experiment_v2.main(args) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["split"] == "holdout" and rep["n_episodes"] == 12
    for cfg in ("v1", "v2"):
        assert "gate" in rep[cfg] and "rule@2" in rep[cfg]["summary"]
    assert set(rep["claims"]) == {
        "S_safety",
        "A_rule_accuracy_v2_minus_v1",
        "F_wasted_view_rate_v2_minus_v1",
        "ablation",
    }
    assert rep["claims"]["A_rule_accuracy_v2_minus_v1"]["2"]["verdict"] in (
        "improved",
        "non-inferior",
        "worse",
    )
    # budget 1: every method of a configuration answers identically
    s = rep["v2"]["summary"]
    assert (
        len({round(s[f"{m}@1"]["accuracy"], 9) for m in ("single", "random", "rule", "oracle")})
        == 1
    )
    with pytest.raises(SystemExit):
        experiment_v2.main(args)  # one shot
