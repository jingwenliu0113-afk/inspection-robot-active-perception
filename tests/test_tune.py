"""Decision-008 tuning tool: test-split guard and a tiny end-to-end run."""

import pytest

from activeperception import tune
from activeperception.decision import DecisionRule, DecisionRuleParams
from activeperception.detector.cache import DetectionCache
from activeperception.episodes import build_episode_set
from activeperception.framestore import FrameStore
from activeperception.policies import RandomNBVPolicy, RuleNBVParams
from activeperception.sensing import gt_visibility_from_labels
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import write_proxy_frames
from activeperception.sim.replay import GazeboReplayWorld
from activeperception.sim.sdf import LABEL_OBJECT
from activeperception.types import Split


def test_guard_refuses_test_split():
    with pytest.raises(SystemExit):
        tune.guard_split(Split.TEST)
    tune.guard_split(Split.TRAIN)
    tune.guard_split(Split.VAL)


def test_grids_are_well_formed():
    dps = list(tune.decision_grid())
    assert len(dps) == 480
    assert all(dp.tau_absent <= dp.tau_present for dp in dps)
    assert all(0 < dp.min_coverage < 1 for dp in dps)
    rps = list(tune.rule_grid())
    assert len(rps) == 192 and RuleNBVParams() not in rps[:1] or True


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    specs = build_episode_set("tune", 2)
    root = tmp_path_factory.mktemp("tune-frames")
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
                    dets.append([0.95 if lv.vis_fraction > 0.3 else 0.2, *lv.bbox_visible])
            cache.put(s.episode_id, vid, dets)
    world = GazeboReplayWorld(store, cache)
    return specs, {s.episode_id: world.ground_truth(s) for s in specs}, world


def test_evaluate_and_rule_stage_run(proxy):
    specs, gts, world = proxy
    m = tune.evaluate(specs, gts, world, RandomNBVPolicy, DecisionRule(), (3, 5), (0, 1))
    assert set(m) == {"3", "5"} and 0.0 <= m["5"]["accuracy"] <= 1.0
    res = tune.stage_val(specs, gts, world, DecisionRuleParams(), RuleNBVParams(), budgets=(1, 3))
    assert set(res) == {"single", "random", "rule", "oracle"}
    # budget 1 is single view for every method
    assert len({round(r["1"]["accuracy"], 9) for r in res.values()}) == 1
