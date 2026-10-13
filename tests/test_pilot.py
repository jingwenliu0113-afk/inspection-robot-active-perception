"""Pilot checks (SPEC §9) on ray-cast proxy frames."""

import json

import pytest

from activeperception import pilot
from activeperception.decision import DecisionRule
from activeperception.detector.cache import DetectionCache
from activeperception.episodes import build_episode_set
from activeperception.framestore import FrameStore
from activeperception.sensing import gt_visibility_from_labels
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import write_proxy_frames
from activeperception.sim.replay import GazeboReplayWorld
from activeperception.sim.sdf import LABEL_OBJECT

PROXY = SyntheticWorld().params.proxy_radius


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    specs = build_episode_set("pilot", 2)
    a = tmp_path_factory.mktemp("pa")
    b = tmp_path_factory.mktemp("pb")
    for s in specs:
        write_proxy_frames(s, a, PROXY)
        write_proxy_frames(s, b, PROXY)
    store = FrameStore(a)
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
    world = GazeboReplayWorld(store, cache)
    gts = {s.episode_id: world.ground_truth(s) for s in specs}
    records = pilot.run_policies(specs, gts, world, DecisionRule(), [1, 3])
    return specs, gts, world, store, FrameStore(b), records


def test_determinism_check(setup):
    specs, _, _, store, rerender, _ = setup
    ids = [s.episode_id for s in specs]
    assert pilot.check_determinism(store, rerender, ids)["pass"]
    assert not pilot.check_determinism(store, rerender, [])["pass"]


def test_timestamp_and_transform_checks(setup):
    specs, _, _, store, _, _ = setup
    assert pilot.check_timestamps(store, specs)["pass"]
    assert pilot.check_transform(store, specs, PROXY)["pass"]


def test_candidate_and_grader_checks(setup):
    specs, gts, _, _, _, records = setup
    assert pilot.check_same_candidates(specs, records)["pass"]
    g = pilot.check_grader(specs, gts, records)
    assert g["pass"] and set(g["confusion"]) == {f"{p}@{b}" for p, b in records}


def test_live_consistency(tmp_path, setup):
    _, _, _, _, _, records = setup
    rec = records[("rule", 3)][0]
    run = {
        "policy": "rule",
        "budget": 3,
        "viewpoint_sequence": list(rec.viewpoint_sequence),
        "decision": str(rec.decision),
        "max_conf_per_view": [o.max_confidence + 1e-4 for o in rec.observations],
    }
    (tmp_path / f"{rec.episode_id}.json").write_text(
        json.dumps({"episode_id": rec.episode_id, "runs": [run]})
    )
    ok = pilot.check_live_consistency(tmp_path, records)
    assert ok["pass"] and ok["runs_compared"] == 1
    run["decision"] = "absent" if run["decision"] != "absent" else "present"
    (tmp_path / f"{rec.episode_id}.json").write_text(
        json.dumps({"episode_id": rec.episode_id, "runs": [run]})
    )
    assert not pilot.check_live_consistency(tmp_path, records)["pass"]
