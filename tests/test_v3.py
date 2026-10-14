"""v3 development components (decision 024): see-through-v3, zone gating, distractor scenes."""

import dataclasses
import math

import numpy as np
import pytest

from activeperception import frozen_v2
from activeperception.serialize import load_spec_set, spec_digest, spec_from_dict, to_dict
from activeperception.types import Decision, Detection, Observation, Pose
from activeperception.v3 import eval as v3e
from activeperception.v3 import geometry as g
from activeperception.v3 import scenes


@pytest.fixture(scope="module")
def spec():
    return load_spec_set("data/episodes/specs-nav-b1.json")[0][1]


def planar_wall(spec, vp, dist: float) -> np.ndarray:
    return np.full((spec.camera.height, spec.camera.width), dist, np.float32)


def test_see_through_v3_tolerates_missing_pixels_but_not_obstacles(spec):
    vp = spec.candidate_viewpoints[0]
    far = planar_wall(spec, vp, 9.0)
    clear = np.array(g.location_visibility_v3(far, spec.camera, vp.pose, spec.zone))
    assert (clear > 0).any()
    holes = far.copy()
    holes[np.random.default_rng(0).random(holes.shape) < 0.2] = np.nan
    v3 = np.array(g.location_visibility_v3(holes, spec.camera, vp.pose, spec.zone))
    from activeperception.sensing import location_visibility_from_depth

    v2 = np.array(location_visibility_from_depth(holes, spec.camera, vp.pose, spec.zone))
    assert (v3 >= 1).sum() > (v2 >= 1).sum()  # one hole no longer blocks a location
    blind = np.full_like(far, np.nan)
    assert not np.any(g.location_visibility_v3(blind, spec.camera, vp.pose, spec.zone))
    near = planar_wall(spec, vp, 0.8)  # something in front of the whole zone
    assert not np.any(g.location_visibility_v3(near, spec.camera, vp.pose, spec.zone))
    # one close pixel in a neighbourhood blocks the axis point (all valid pixels must agree)
    spot = far.copy()
    spot[::3, ::3] = 0.8
    assert not np.any(
        np.array(g.location_visibility_v3(spot, spec.camera, vp.pose, spec.zone)) >= 1
    )


def det(conf, box):
    return Detection(confidence=conf, bbox=box, area_frac=0.1, center_uv=(0.5, 0.5))


def test_locate_detection_and_gate(spec):
    vp = spec.candidate_viewpoints[0]
    cam, z = spec.camera, spec.zone
    # depth of the ground point straight below the image centre column at the zone centre
    d_zone = math.hypot(vp.pose.x - z.cx, vp.pose.y - z.cy) * math.cos(vp.pose.pitch)
    depth = np.full((cam.height, cam.width), d_zone, np.float32)
    box = (300.0, 200.0, 340.0, 280.0)
    xy = v3e.locate_detection(det(0.9, box), depth, cam, vp.pose)
    assert math.hypot(xy[0] - z.cx, xy[1] - z.cy) < z.radius + v3e.ZONE_SLACK_M
    far = np.full_like(depth, 6.0)
    out = v3e.gate([det(0.9, box)], far, cam, vp.pose, z)
    assert out["flags"] == ["out"] and out["c_in"] == 0.0 and out["c_block"] == 0.0
    unknown = v3e.gate([det(0.4, box)], np.full_like(depth, np.nan), cam, vp.pose, z)
    assert unknown["flags"] == ["unknown"] and unknown["c_in"] == 0.0 and unknown["c_block"] == 0.4


def obs(c_in, c_block, cleared):
    vp = dataclasses.replace(
        load_spec_set("data/episodes/specs-nav-b1.json")[0][0].initial_viewpoint
    )
    vis = tuple([1.0 if cleared else 0.0] * 64)
    return Observation(
        0, vp, (), 1.0, 0.0, location_visibility=vis, meta={"c_in": c_in, "c_block": c_block}
    )


def test_decision_v3_uses_only_located_detections():
    rule = v3e.DecisionRuleV3(frozen_v2.DECISION_V2)
    assert rule.decide(None, [obs(0.95, 0.95, False)]).decision == Decision.PRESENT
    assert rule.decide(None, [obs(0.0, 0.0, True)]).decision == Decision.ABSENT
    # a confident detection outside the zone neither makes 'present' nor blocks 'absent'
    assert rule.decide(None, [obs(0.0, 0.0, True)]).decision == Decision.ABSENT
    # an unlocatable weak detection blocks 'absent' (conservative)
    assert rule.decide(None, [obs(0.0, 0.3, True)]).decision == Decision.INCONCLUSIVE
    assert rule.decide(None, [obs(0.5, 0.5, False)]).decision == Decision.INCONCLUSIVE


def test_decision_v3_without_gate_data_is_decision_v2(spec):
    from activeperception.decision import DecisionRuleV2

    o = Observation(
        0,
        spec.initial_viewpoint,
        (det(0.8, (0, 0, 10, 10)),),
        1.0,
        0.0,
        location_visibility=(1.0,) * 64,
    )
    v3 = v3e.DecisionRuleV3(frozen_v2.DECISION_V2).decide(None, [o])
    v2 = DecisionRuleV2(frozen_v2.DECISION_V2).decide(None, [o])
    assert v3.decision == v2.decision == Decision.PRESENT


def test_distractors_serialise_and_leave_old_specs_unchanged(spec):
    assert "distractors" not in to_dict(spec)["layout"]
    with_dx = dataclasses.replace(
        spec, layout=dataclasses.replace(spec.layout, distractors=(Pose(3, 0, 0, 1, 0),))
    )
    d = to_dict(with_dx)
    assert d["layout"]["distractors"][0]["x"] == 3
    assert spec_from_dict(d) == with_dx and spec_from_dict(to_dict(spec)) == spec
    assert spec_digest(with_dx) != spec_digest(spec)


def test_distractor_placement_keeps_clear():
    specs = scenes.distractor_specs("v3-test-dx", 6)
    for s in specs:
        (p,) = s.layout.distractors
        r = math.hypot(p.x - s.zone.cx, p.y - s.zone.cy)
        assert r > s.zone.radius + v3e.ZONE_SLACK_M + 0.15
        assert scenes._ok(p.x, p.y, s)
    by_group = {}
    for s in specs:
        by_group.setdefault(s.scene_group, set()).add(s.layout.distractors)
    assert all(len(v) == 1 for v in by_group.values())  # same distractor for all variants


def test_v2_geometry_config_is_decision_016():
    assert v3e.CONFIGS["v2"] is g.V2_GEOMETRY
    assert not g.V2_GEOMETRY.see_v3 and not g.V2_GEOMETRY.scale and not g.V2_GEOMETRY.weights
    assert g.V2_GEOMETRY.margin_ok == (0.015, 0.005)
