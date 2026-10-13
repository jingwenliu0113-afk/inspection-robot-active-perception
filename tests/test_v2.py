"""v2 (decision 011): free-space absent rule, known-space NBV, oracle-v2."""

import dataclasses
import math

import numpy as np
import pytest

from activeperception.decision import Decision, DecisionRuleV2, DecisionRuleV2Params
from activeperception.episodes import GeneratorConfig, build_episode_set, generate_episode
from activeperception.harness import run_episode
from activeperception.policies import OracleNBVv2Policy, RuleNBVv2Params, RuleNBVv2Policy
from activeperception.policies.rule_nbv_v2 import KnownMap
from activeperception.sensing import (
    LOCATION_SAMPLES,
    cleared_locations,
    location_grid,
    location_visibility_from_depth,
)
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import render_spec
from activeperception.types import Detection, Observation, Pose, Viewpoint

WORLD = SyntheticWorld()
PROXY = WORLD.params.proxy_radius
FULL = tuple([1.0] * LOCATION_SAMPLES)


def _obs(vid, az, conf=None, loc=(), cells=()):
    pose = Pose(2 * math.cos(az), 2 * math.sin(az), 1.0, az + math.pi, 0.2)
    vp = Viewpoint(vid, pose, az % (2 * math.pi), 2.0, 1.0)
    dets = () if conf is None else (Detection(conf, (0, 0, 10, 10), 0.001, (0.5, 0.5)),)
    return Observation(vid, vp, dets, 1.0, 0.0, location_visibility=loc, obstacle_cells=cells)


def test_location_grid_inside_zone_margin():
    zone = GeneratorConfig().zone
    g = location_grid(zone)
    assert g.shape == (LOCATION_SAMPLES, 2)
    assert (np.hypot(g[:, 0] - zone.cx, g[:, 1] - zone.cy) <= zone.radius - 0.2 + 1e-9).all()


def test_present_object_is_never_seen_through_everywhere():
    """Safety property: union over all 13 views never clears every location."""
    for spec in build_episode_set("safe", 25)[::2]:  # present variants
        vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
        analytic = np.array([WORLD.location_visibility(spec, v) for v in vps])
        assert not (analytic >= 1.0).any(axis=0).all()
    for spec in build_episode_set("safe-d", 6)[::2]:
        vps = [spec.initial_viewpoint, *spec.candidate_viewpoints]
        depth = np.array(
            [
                location_visibility_from_depth(
                    render_spec(spec, v.pose, PROXY)[0], spec.camera, v.pose, spec.zone
                )
                for v in vps
            ]
        )
        assert not (depth >= 1.0).any(axis=0).all()


def test_depth_and_analytic_location_visibility_agree():
    agree, n = 0, 0
    for spec in build_episode_set("agree", 4):
        for v in [spec.initial_viewpoint, *spec.candidate_viewpoints[::4]]:
            a = np.array(WORLD.location_visibility(spec, v))
            d = np.array(
                location_visibility_from_depth(
                    render_spec(spec, v.pose, PROXY)[0], spec.camera, v.pose, spec.zone
                )
            )
            agree += int(((a >= 1.0) == (d >= 1.0)).sum())
            n += len(a)
    assert agree / n > 0.97


def test_clear_absent_view_sees_through_every_location():
    cfg = dataclasses.replace(GeneratorConfig(), n_occluders_range=(0, 0), p_block_initial=0.0)
    for g in range(4):
        spec = generate_episode("clear2", g, 1, cfg)
        assert WORLD.location_visibility(spec, spec.initial_viewpoint) == FULL


def test_decision_v2_truth_table():
    rule = DecisionRuleV2()
    dep = generate_episode("dv2", 0, 0).deployable()
    assert rule.decide(dep, [_obs(-1, 0.0, conf=0.9)]).decision == Decision.PRESENT
    out = rule.decide(dep, [_obs(-1, 0.0, loc=FULL)])
    assert out.decision == Decision.ABSENT and out.confidence == 1.0
    weak = rule.decide(dep, [_obs(-1, 0.0, conf=0.1, loc=FULL)])
    assert weak.decision == Decision.INCONCLUSIVE  # a weak detection blocks absent
    half = tuple([1.0] * (LOCATION_SAMPLES // 2) + [0.0] * (LOCATION_SAMPLES // 2))
    assert rule.decide(dep, [_obs(-1, 0.0, loc=half)]).decision == Decision.INCONCLUSIVE
    other = tuple([0.0] * (LOCATION_SAMPLES // 2) + [1.0] * (LOCATION_SAMPLES // 2))
    both = rule.decide(dep, [_obs(-1, 0.0, loc=half), _obs(3, 1.0, loc=other)])
    assert both.decision == Decision.ABSENT  # the union of views counts
    # no see-through evidence (e.g. v1-era observation) -> never absent
    assert rule.decide(dep, [_obs(-1, 0.0)]).decision == Decision.INCONCLUSIVE
    lenient = DecisionRuleV2(DecisionRuleV2Params(tau_clear=0.5))
    assert lenient.decide(dep, [_obs(-1, 0.0, loc=half)]).decision == Decision.ABSENT


def test_col_min_threshold():
    two_thirds = tuple([2 / 3] * LOCATION_SAMPLES)
    assert cleared_locations([_obs(-1, 0.0, loc=two_thirds)], 1.0).sum() == 0
    assert cleared_locations([_obs(-1, 0.0, loc=two_thirds)], 2 / 3).all()


def test_known_map_free_occupied_unknown():
    spec = generate_episode("km", 0, 1)
    dep = spec.deployable()
    # one visited camera on +x looking at the zone; a wall of obstacle cells at x = 1.0
    cells = tuple((20, iy, 150) for iy in range(-4, 5))
    h = [_obs(-1, 0.0, cells=cells)]
    km = KnownMap(dep, h)
    assert km._lookup(km.free, np.array([1.5]), np.array([0.1]))[0]  # in the wedge, before the wall
    assert not km._lookup(km.free, np.array([1.5]), np.array([0.6]))[0]  # outside the 60 deg wedge
    assert not km._lookup(km.free, np.array([0.8]), np.array([0.0]))[0]  # behind the wall
    pose_back = Pose(-2.0, 0.0, 1.0, 0.0, 0.2)  # opposite side: line to zone is unknown
    pose_front = Pose(2.0, 0.0, 1.0, math.pi, 0.2)  # behind the wall from its own camera
    target = np.array([[0.0, 0.0]])
    assert km.sight_status(dep, pose_front, target)[0] == 0
    assert km.sight_status(dep, pose_back, target)[0] in (1, 2)


def test_rule_v2_prefers_seeing_uncleared_locations(world=WORLD):
    spec = generate_episode("pref", 2, 1)
    dep = spec.deployable()
    pol = RuleNBVv2Policy(RuleNBVv2Params(w_gain=1.0, w_novelty=0.0), DecisionRuleV2Params())
    pol.reset(dep, 0)
    h = [world.observe(spec, spec.initial_viewpoint)]
    uncleared = ~cleared_locations(h, 1.0)
    gains = {
        vp.id: pol.features(dep, h, vp, uncleared)["clear_gain"] for vp in spec.candidate_viewpoints
    }
    assert pol.select_next(dep, h, 3) == max(sorted(gains), key=lambda k: gains[k])
    assert all(0.0 <= g <= 1.0 for g in gains.values())


def test_oracle_v2_reads_future_views_only_through_peek():
    # an absent episode whose initial view cannot see through every location
    spec = next(
        s
        for s in build_episode_set("ov2", 20)
        if not s.layout.object_present
        and min(WORLD.location_visibility(s, s.initial_viewpoint)) < 1.0
    )
    gts = {spec.episode_id: WORLD.ground_truth(spec)}
    calls = []

    def peek(eid, vid):
        calls.append(vid)
        vp = spec.initial_viewpoint if vid == -1 else spec.deployable().candidate(vid)
        return WORLD.observe(spec, vp)

    pol = OracleNBVv2Policy(gts.__getitem__, peek, DecisionRuleV2Params())
    rec = run_episode(spec, WORLD, pol, DecisionRuleV2(), 3)
    assert calls and set(calls) <= {vp.id for vp in spec.candidate_viewpoints}
    assert rec.viewpoints_used <= 3


@pytest.mark.parametrize("budget", [2, 3, 5])
def test_v2_never_false_absent_on_synthetic(budget):
    rule = DecisionRuleV2()
    for spec in build_episode_set("fa2", 15):
        pol = RuleNBVv2Policy(RuleNBVv2Params(), DecisionRuleV2Params())
        rec = run_episode(spec, WORLD, pol, rule, budget)
        if spec.layout.object_present:
            assert rec.decision != Decision.ABSENT
