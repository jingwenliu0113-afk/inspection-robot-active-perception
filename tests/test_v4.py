"""v4 development components (decision 029): wider pose search, scale hypotheses."""

import dataclasses
import math

import numpy as np
import pytest

from activeperception.nav import localize, scene
from activeperception.serialize import load_spec_set
from activeperception.v3 import eval as v3e
from activeperception.v3 import geometry as g3
from activeperception.v3.frozen_v3 import GEOMETRY
from activeperception.v4 import configs
from activeperception.v4.geometry import margin_for_v4, refine_pose_v4


@pytest.fixture(scope="module")
def spec():
    return load_spec_set("data/episodes/specs-nav-b1.json")[0][0]


def _depth(spec, pose, scale=1.0):
    from activeperception.sim.raycast import render

    depth, _ = render(spec.camera, pose, (*spec.layout.occluders, *scene.walls()), None)
    return (depth * scale).astype(np.float32)


def _err(ref, truth):
    return math.hypot(ref.pose.x - truth.x, ref.pose.y - truth.y)


def test_v4_with_defaults_is_frozen_v3(spec):
    truth = spec.candidate_viewpoints[3].pose
    depth = _depth(spec, truth, 1.015)
    for dx, dy, dyaw in ((0.05, -0.03, 0.03), (0.12, 0.10, -0.05), (0.0, 0.0, 0.0)):
        est = dataclasses.replace(truth, x=truth.x + dx, y=truth.y + dy, yaw=truth.yaw + dyaw)
        args = (depth, spec.camera, est, spec.zone, localize.map_outlines(spec))
        r3 = g3.refine_pose_v3(*args, GEOMETRY, prior=(0.06, 0.04))
        r4 = refine_pose_v4(*args, configs.BASE, prior=(0.06, 0.04))
        for f in dataclasses.fields(r3):
            assert getattr(r3, f.name) == getattr(r4, f.name), f.name
        assert margin_for_v4(r4, configs.BASE, (0.06, 0.04)) == g3.margin_for(
            r3, GEOMETRY, (0.06, 0.04)
        )


def test_window_covering_the_prior_turns_a_far_estimate_into_a_conflict(spec):
    """decision 026 V4: with L2 (sigma 6 cm) v3 searched +-15 cm, so the 3-sigma gate (18 cm) never
    fired. v4 searches +-4 sigma: the correct fit to a 20 cm-off estimate moves > 3 sigma."""
    truth = spec.candidate_viewpoints[3].pose
    depth = _depth(spec, truth)
    prior = (0.06, 0.04)
    far = dataclasses.replace(truth, x=truth.x + 0.20, y=truth.y - 0.05)
    args = (depth, spec.camera, far, spec.zone, localize.map_outlines(spec))
    w4 = configs.CONFIGS["w4"]
    r = refine_pose_v4(*args, w4, prior=prior)
    assert r.window_xy == pytest.approx(0.24)
    assert abs(r.dx + 0.20) < 0.01  # found the truth ...
    assert not r.ok and r.conflict and g3.blind(r, w4)  # ... beyond the gate -> clears nothing
    near = dataclasses.replace(truth, x=truth.x + 0.12, y=truth.y - 0.05)
    r = refine_pose_v4(
        depth, spec.camera, near, spec.zone, localize.map_outlines(spec), w4, prior=prior
    )
    assert r.ok and _err(r, truth) < 0.01
    # L1 (sigma 3 cm): 4 sigma = 12 cm < v3's 15 cm -> the window stays v3's
    r = refine_pose_v4(
        depth, spec.camera, near, spec.zone, localize.map_outlines(spec), w4, prior=(0.03, 0.02)
    )
    assert r.window_xy == localize.SEARCH_XY_M


def test_scale_hypotheses_widen_the_margin_by_their_spread(spec):
    truth = spec.candidate_viewpoints[3].pose
    depth = _depth(spec, truth, 0.97)  # the camera under-reads range by 3 % (D435-like)
    est = dataclasses.replace(truth, x=truth.x + 0.03, yaw=truth.yaw - 0.02)
    cfg = configs.CONFIGS["w4h"]
    r = refine_pose_v4(
        depth, spec.camera, est, spec.zone, localize.map_outlines(spec), cfg, prior=(0.03, 0.02)
    )
    assert r.ok and _err(r, truth) < 0.02
    assert abs(r.scale - 0.97) <= 0.011
    mx, myaw = margin_for_v4(r, cfg, (0.03, 0.02))
    assert mx == pytest.approx(cfg.margin_ok[0] + r.spread_xy)
    assert myaw == pytest.approx(cfg.margin_ok[1] + r.spread_yaw)
    blind_cfg = dataclasses.replace(cfg, hyp_blind_m=r.spread_xy / 2) if r.spread_xy > 0 else None
    if blind_cfg is not None:
        rb = refine_pose_v4(
            depth,
            spec.camera,
            est,
            spec.zone,
            localize.map_outlines(spec),
            blind_cfg,
            prior=(0.03, 0.02),
        )
        assert not rb.ok and rb.ambiguous and g3.blind(rb, blind_cfg)


def test_shared_harness_resolves_v4_configs_and_still_refuses_formal_data():
    assert v3e.config("w4h") is configs.CONFIGS["w4h"]
    assert v3e.config("v3") is GEOMETRY
    for ns in ("v3", "v3-dx", "detv2-sim", "r0b", "nav-b2"):
        with pytest.raises(SystemExit):
            v3e.main(["--ns", ns, "--configs", "w4h", "--out", "/tmp/never"])


def test_frozen_v4_is_the_development_choice():
    from activeperception.v4 import frozen_v4

    assert frozen_v4.GEOMETRY == dataclasses.replace(configs.CONFIGS["w4hjg8"], name="v4")
    assert frozen_v4.GEOMETRY.gate_band == 0.08
    assert v3e.config("v4") is frozen_v4.GEOMETRY
    g = frozen_v4.GEOMETRY
    assert g.window_k == 4.0 and g.scale_jacobian and not g.scale_edge
    assert g.hyp_scales == (0.96, 0.98, 1.0, 1.02, 1.04) and g.hyp_blind_m == math.inf
    assert (g.margin_ok, g.prior_k, g.on_conflict) == ((0.06, 0.03), 3.0, "blind")  # as v3
    assert frozen_v4.describe()["detector"].startswith("detector-v1")


def _fake(safe=True, absent=1.0, exceed=0):
    s = {
        f"{m}@{b}": {
            "accuracy": 1.0,
            "false_absent": 0,
            "false_present": 0,
            "geometric_risk": 0,
            "accuracy_by_state": {"absent": absent},
        }
        for m in ("rule",)
        for b in (2, 3, 5)
    }
    return {
        "summary": s,
        "false_absent": 0,
        "false_present": 0,
        "geometric_risk": 0,
        "all_views_geometric_risk": [],
        "occupied_false_clearance": {"views": 0 if safe else 1, "present_views": 1040},
        "exceed": {"refined_ok": exceed},
    }


def test_v4_formal_verdicts_follow_the_preregistered_rules():
    from activeperception.v4 import formal

    res = {}
    for ns, d, p, prior in formal.CONDITIONS:
        res[formal.key(ns, d, p, prior, "v3")] = _fake(exceed=40)
        res[formal.key(ns, d, p, prior, "v4")] = _fake(exceed=10)
    ver = formal.verdicts(res)
    assert all(ver[k]["pass"] for k in ("W1", "W2", "W3", "W4", "W5", "W6", "D1"))
    assert "pass" not in ver["R1"]  # report only
    res[formal.key("v4", "D2", "L2", None, "v4")] = _fake(safe=False, exceed=11)
    ver = formal.verdicts(res)
    assert not ver["W3"]["pass"] and not ver["W5"]["pass"]  # 11 > 0.25 x 40
    res[formal.key("v4", "D3", "L1", None, "v3")] = _fake(safe=False, exceed=40)
    res[formal.key("v4", "D1", "L1", None, "v4")] = _fake(absent=0.85)
    ver = formal.verdicts(res)
    assert not ver["D1"]["pass"] and not ver["W2"]["pass"] and ver["W1"]["pass"]


def test_v4_formal_runner_uses_only_its_new_namespaces():
    from activeperception.v4 import formal

    assert {j[0] for j in formal.jobs()} == {"v4", "v4-dx"}
    assert {j[3] for j in formal.jobs()} == {"v3", "v4"}
    assert len(formal.jobs()) == 16


def test_band_gating_needs_the_whole_depth_band_in_the_zone_to_make_present():
    from activeperception.types import Detection
    from activeperception.v4.geometry import gate_band

    spec = load_spec_set("data/episodes/specs-nav-b1.json")[0][1]
    vp, cam, z = spec.candidate_viewpoints[0], spec.camera, spec.zone
    box = (300.0, 200.0, 340.0, 280.0)
    dets = [Detection(confidence=0.9, bbox=box, area_frac=0.1, center_uv=(0.5, 0.5))]
    rng = math.hypot(vp.pose.x - z.cx, vp.pose.y - z.cy)

    def located(d):
        depth = np.full((cam.height, cam.width), d, np.float32)
        xy = v3e.locate_detection(dets[0], depth, cam, vp.pose)
        return depth, math.hypot(xy[0] - z.cx, xy[1] - z.cy)

    limit = z.radius + v3e.ZONE_SLACK_M
    for d in np.linspace(0.6, 1.6, 41) * rng:  # walk the detection along the ray through the zone
        depth, dist = located(d)
        nominal = v3e.gate(dets, depth, cam, vp.pose, z)
        assert gate_band(dets, depth, cam, vp.pose, z, 0.0, v3e.ZONE_SLACK_M) == nominal
        band = gate_band(dets, depth, cam, vp.pose, z, 0.08, v3e.ZONE_SLACK_M)
        _, lo = located(d * 0.92)
        _, hi = located(d * 1.08)
        if max(lo, hi) <= limit:
            assert band["flags"] == ["in"] and band["c_in"] == 0.9
        elif dist <= limit or min(lo, hi) <= limit:
            assert band["flags"] == ["maybe"] and band["c_in"] == 0.0 and band["c_block"] == 0.9
    flags = {
        gate_band(dets, located(d)[0], cam, vp.pose, z, 0.08, v3e.ZONE_SLACK_M)["flags"][0]
        for d in np.linspace(0.6, 1.6, 41) * rng
    }
    assert flags == {"in", "maybe", "out"}
