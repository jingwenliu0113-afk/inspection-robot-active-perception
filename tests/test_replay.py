"""Frame store, detection cache and the Gazebo replay world, on ray-cast proxy frames."""

import dataclasses

import numpy as np
import pytest

from activeperception.decision import DecisionRule
from activeperception.detector.cache import DetectionCache
from activeperception.episodes import build_episode_set
from activeperception.framestore import (
    DEPTH_NO_RETURN,
    EpisodeFrames,
    FrameStore,
    decode_depth_mm,
    encode_depth_mm,
)
from activeperception.harness import run_episode
from activeperception.policies import (
    OracleNBVPolicy,
    RandomNBVPolicy,
    RuleNBVPolicy,
    SingleViewPolicy,
)
from activeperception.sensing import gt_visibility_from_labels
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import write_proxy_frames
from activeperception.sim.replay import FrameMismatchError, GazeboReplayWorld
from activeperception.sim.sdf import LABEL_OBJECT
from activeperception.types import GroundTruthState

SYN = SyntheticWorld()
PROXY = SYN.params.proxy_radius


@pytest.fixture(scope="module")
def proxy_store(tmp_path_factory):
    specs = build_episode_set("replay", 3)
    root = tmp_path_factory.mktemp("frames")
    for s in specs:
        write_proxy_frames(s, root, PROXY)
    store = FrameStore(root)
    # detections derived from the labels (a stand-in detector): confidence = visible fraction
    cache = DetectionCache("label-oracle-test", {"note": "test double"})
    for s in specs:
        fr = store.episode(s.episode_id)
        for vid in fr.viewpoint_ids:
            clear = fr.labels_clear(vid)
            dets = []
            if clear is not None:
                lv = gt_visibility_from_labels(fr.labels(vid), clear, LABEL_OBJECT)
                if lv.bbox_visible is not None:
                    dets.append([lv.vis_fraction, *lv.bbox_visible])
            cache.put(s.episode_id, vid, dets)
    return specs, store, cache


def test_depth_codec_roundtrip():
    d = np.array([[0.0, 1.2344, np.inf], [np.nan, 65.6, 3.0]], dtype=np.float32)
    mm = encode_depth_mm(d)
    assert mm.tolist() == [[0, 1234, DEPTH_NO_RETURN], [0, DEPTH_NO_RETURN, 3000]]
    back = decode_depth_mm(mm)
    assert np.isnan(back[0, 0]) and np.isinf(back[0, 2]) and back[1, 2] == pytest.approx(3.0)


def test_frame_store_contents(proxy_store):
    specs, store, _ = proxy_store
    assert store.episode_ids() == sorted(s.episode_id for s in specs)
    fr = store.episode(specs[0].episode_id)
    assert isinstance(fr, EpisodeFrames)
    assert fr.viewpoint_ids == [-1, *range(12)]
    assert fr.rgb(0).shape == (480, 640, 3) and fr.depth(0).dtype == np.float32
    assert (fr.labels_clear(0) is None) == (not specs[0].layout.object_present)
    with pytest.raises(KeyError):
        fr.rgb(99)


def test_detection_cache_roundtrip(tmp_path, proxy_store):
    _, _, cache = proxy_store
    path = tmp_path / "dets.jsonl"
    cache.save(path)
    back = DetectionCache.load(path)
    assert back.keys() == cache.keys()
    for k in cache.keys():
        assert back.get(*k) == cache.get(*k)  # exact float round trip
    c2 = DetectionCache("x")
    c2.put("e", 0, [[0.2, 0, 0, 10, 10], [0.9, 5, 5, 15, 25]])
    assert [d.confidence for d in c2.get("e", 0)] == [0.9, 0.2]
    assert [d.confidence for d in c2.with_min_confidence(0.5).get("e", 0)] == [0.9]
    assert c2.get("e", 0)[0].area_frac == pytest.approx(200 / (640 * 480))
    with pytest.raises(KeyError):
        c2.get("e", 1)


def test_replay_matches_synthetic_geometry(proxy_store):
    specs, store, cache = proxy_store
    world = GazeboReplayWorld(store, cache)
    for s in specs:
        for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
            assert world.zone_visible_fraction(s, vp) == pytest.approx(
                SYN.zone_visible_fraction(s, vp), abs=0.03
            )
        gt, syn = world.ground_truth(s), SYN.ground_truth(s)
        assert gt.object_present == syn.object_present
        if gt.state == GroundTruthState.ABSENT:
            assert syn.state == GroundTruthState.ABSENT
        assert gt.visibility_initial == pytest.approx(syn.visibility_initial, abs=0.1)


def test_replay_rejects_mismatched_spec(proxy_store):
    specs, store, cache = proxy_store
    world = GazeboReplayWorld(store, cache)
    s = specs[0]
    moved = dataclasses.replace(s, seed=s.seed + 1)
    with pytest.raises(FrameMismatchError):
        world.observe(moved, moved.initial_viewpoint)


@pytest.mark.parametrize("budget", [1, 3, 5])
def test_harness_on_replay_world(proxy_store, budget):
    specs, store, cache = proxy_store
    world = GazeboReplayWorld(store, cache)
    rule = DecisionRule()
    gts = {s.episode_id: world.ground_truth(s) for s in specs}
    policies = [SingleViewPolicy(), RandomNBVPolicy(), RuleNBVPolicy(), OracleNBVPolicy(gts.get)]
    runs = {p.name: [run_episode(s, world, p, rule, budget) for s in specs] for p in policies}
    for recs in runs.values():
        assert all(1 <= r.viewpoints_used <= budget for r in recs)
    if budget == 1:
        base = [(r.decision, r.viewpoint_sequence) for r in runs["single"]]
        for recs in runs.values():
            assert [(r.decision, r.viewpoint_sequence) for r in recs] == base


class _LabelTripwireFrames(EpisodeFrames):
    def labels(self, vp_id):
        raise AssertionError("labels read during a deployable run")

    def labels_clear(self, vp_id):
        raise AssertionError("clear labels read during a deployable run")


class _TripwireStore(FrameStore):
    def episode(self, episode_id):
        return _LabelTripwireFrames(self.path(episode_id))


@pytest.mark.parametrize("policy", [SingleViewPolicy(), RandomNBVPolicy(), RuleNBVPolicy()])
def test_deployable_replay_runs_never_read_labels(proxy_store, policy):
    specs, store, cache = proxy_store
    world = GazeboReplayWorld(_TripwireStore(store.root), cache)
    rule = DecisionRule()
    for s in specs:
        run_episode(s, world, policy, rule, budget=5)
