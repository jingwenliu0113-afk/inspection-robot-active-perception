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


def test_margin_falls_back_to_k_sigma_of_the_localiser():
    est = Pose(0, 0, 1.1, 0, 0.3)
    good = g.RefinementV3(est, True, 0, 0, 0, 1.0, 500, 50.0, 0.0, 0.0)
    bad = dataclasses.replace(good, ok=False)
    cfg = g.GeometryConfig(margin_ok=(0.04, 0.02), prior_k=3.0)
    assert g.margin_for(good, cfg, (0.06, 0.04)) == (0.04, 0.02)
    assert g.margin_for(bad, cfg, (0.06, 0.04)) == pytest.approx((0.18, 0.12))
    assert g.margin_for(bad, cfg, (0.01, 0.005)) == g.MARGIN_FALLBACK  # never below the v2 floor
    assert g.margin_for(bad, g.GeometryConfig(), (0.06, 0.04)) == g.MARGIN_FALLBACK  # gate off


def test_reported_prior_has_a_floor():
    assert v3e.reported_prior("P0") == v3e.PRIOR_FLOOR
    assert v3e.reported_prior("L2") == (0.06, 0.04)


def test_formal_distractor_set_has_its_own_seed_and_split():
    from activeperception.types import Split

    dev = scenes.distractor_specs(scenes.DEV_NAMESPACE, 2)
    formal = scenes.distractor_specs(scenes.FORMAL_NAMESPACE, 2)
    assert {s.split for s in dev} == {Split.R0_DEV}
    assert {s.split for s in formal} == {Split.V3_EVAL}
    assert {s.generator_version for s in formal} == {scenes.GENERATOR_VERSION_FORMAL}
    assert not {s.episode_id for s in dev} & {s.episode_id for s in formal}
    assert dev[0].layout.distractors != formal[0].layout.distractors


def test_dev_eval_refuses_formal_data():
    for ns in ("v3", "v3-dx", "r0b", "nav-b2", "core"):
        with pytest.raises(SystemExit):
            v3e.main(["--ns", ns, "--out", "/nonexistent"])


def test_report_counts_decisions_per_state():
    from activeperception.v3 import report

    r = {
        "rule_per_episode": {
            "a": {"state": "absent", "b2": "inconclusive", "b3": "absent", "b5": "absent"},
            "b": {"state": "unobservable", "b2": "inconclusive", "b3": "present", "b5": "present"},
            "c": {"state": "absent", "b2": "inconclusive", "b3": "inconclusive", "b5": "absent"},
        }
    }
    assert report.by_state(r, 5) == {
        "absent": {"present": 0, "absent": 2, "inconclusive": 0},
        "unobservable": {"present": 1, "absent": 0, "inconclusive": 0},
    }
    assert report.by_state(r, 2)["absent"]["inconclusive"] == 2
    assert report.by_state({}, 5) == {}


def _fake(fa=0, fp=0, occ=0, absent=1.0, ok=True):
    states = {"e1": "absent", "e2": "visible", "e3": "absent", "e4": "visible"}
    right = {"absent": "absent", "visible": "present"}
    per = {e: {"state": st, **{f"b{b}": right[st] for b in (2, 3, 5)}} for e, st in states.items()}
    summary = {
        f"{m}@{b}": {
            "accuracy": 1.0,
            "false_absent": fa if (m, b) == ("rule", 2) else 0,
            "false_present": fp if (m, b) == ("rule", 2) else 0,
            "geometric_risk": 0,
            "accuracy_by_state": {"absent": absent, "visible": 1.0},
        }
        for m in ("single", "random", "rule", "oracle")
        for b in range(1, 6)
    }
    return {
        "job": {"config": "v3", "gated": True},
        "summary": summary,
        "false_absent": fa,
        "false_present": fp,
        "geometric_risk": 0,
        "all_views_geometric_risk": [],
        "occupied_false_clearance": {"views": occ, "present_views": 10},
        "rule_per_episode": per,
        "pose_error_m": {"p50": 0.0, "p95": 0.0, "max": 0.0},
        "refine_ok": 1.0,
    }


def test_formal_verdicts_follow_the_preregistered_rules():
    from activeperception.v3 import formal

    assert len(formal.jobs()) == 12 and formal.PIPELINES["v3"][1] is True  # zone gating on
    res = {}
    for ns, d, p, prior in formal.CONDITIONS:
        for pipe in formal.PIPELINES:
            res[formal.key(ns, d, p, prior, pipe)] = _fake()
    ver = formal.verdicts(res)
    assert all(ver[k]["pass"] for k in ("V1", "V2", "V3", "V4", "V5"))
    typical = formal.key("v3", "D1", "L1", None, "v3")
    for bad, failed in (
        (_fake(occ=1), "V1"),
        (_fake(fp=1), "V1"),
        (_fake(absent=0.89), "V2"),
    ):
        ver = formal.verdicts({**res, typical: bad})
        assert not ver[failed]["pass"]
    dx = formal.key("v3-dx", "D1", "L1", None, "v3")
    assert not formal.verdicts({**res, dx: _fake(fp=3)})["V3"]["pass"]
    assert formal.verdicts({**res, formal.key("v3", "D1", "L1", None, "v2"): _fake(fp=3)})["V1"][
        "pass"
    ]  # v2 is the comparison, never judged
    groups = {e: i for i, e in enumerate(("e1", "e2", "e3", "e4"))}
    diff = formal.paired(res, groups)
    assert diff["v3:D1xL1"]["rule@2"]["mean"] == 0.0
    assert "V1" in formal.markdown(res, formal.verdicts(res), diff)


def test_frozen_v3_is_the_development_choice():
    from activeperception.v3 import frozen_v3

    assert dataclasses.replace(frozen_v3.GEOMETRY, name="m6c") == v3e.CONFIGS["m6c"]
    assert frozen_v3.TIE_BREAK is False and v3e.config("v3") is frozen_v3.GEOMETRY


def test_conflicting_fit_makes_the_view_blind_only_when_configured():
    est = Pose(0, 0, 1.1, 0, 0.3)
    ok = g.RefinementV3(est, True, 0, 0, 0, 1.0, 500, 50.0, 0.0, 0.0)
    conflict = dataclasses.replace(ok, ok=False, conflict=True)
    degenerate = dataclasses.replace(ok, ok=False)
    c = v3e.CONFIGS["m6c"]
    assert not g.blind(ok, c) and g.blind(conflict, c) and not g.blind(degenerate, c)
    assert not g.blind(conflict, v3e.CONFIGS["m6p"])
    assert g.blind(degenerate, v3e.CONFIGS["m6b"])
