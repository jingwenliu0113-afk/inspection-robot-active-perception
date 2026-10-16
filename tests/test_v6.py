"""H-P development candidates (decision 037 appendix A): the arms, the cost-ratio rule and the
harness plumbing of B0 / H-P / B-floor / Oracle-pose."""

import dataclasses
import math
from types import SimpleNamespace

import numpy as np
import pytest

from activeperception.serialize import load_spec_set
from activeperception.v3 import eval as v3e
from activeperception.v5 import frozen_v5
from activeperception.v6 import configs, dev, hp


@pytest.fixture(scope="module")
def spec():
    return load_spec_set("data/episodes/specs-nav-b1.json")[0][0]


def _render(spec, pose):
    from activeperception.nav import scene
    from activeperception.sim.raycast import render

    depth, _ = render(spec.camera, pose, (*spec.layout.occluders, *scene.walls()), None)
    return depth.astype(np.float32)


def test_reported_prior_floor_only_changes_p0():
    assert v3e.reported_prior("P0") == v3e.PRIOR_FLOOR
    assert v3e.reported_prior("P0", configs.FLOOR) == configs.FLOOR == (0.03, 0.015)
    for level in ("L1", "L2"):  # their sigmas are already >= the raised floor
        assert v3e.reported_prior(level, configs.FLOOR) == v3e.reported_prior(level)


def test_trust_rule():
    assert hp.trusts_localiser(1.0, 1.2) and hp.trusts_localiser(1.2, 1.2)
    assert not hp.trusts_localiser(1.2001, 1.2)
    assert not hp.trusts_localiser(None, 1.2)
    assert not hp.trusts_localiser(math.inf, 1.2) and not hp.trusts_localiser(math.nan, 1.2)


def test_each_arm_is_frozen_v5_with_one_change():
    v5 = frozen_v5.GEOMETRY
    assert configs.ARMS["B0"] is v5
    expected = {
        "HP12": {"hp_c": 1.2},
        "HP13": {"hp_c": 1.3},
        "Bfloor": {"prior_floor": (0.03, 0.015)},
        "Oracle": {"oracle_pose": True},
    }
    defaults = {"hp_c": 0.0, "prior_floor": None, "oracle_pose": False}
    for arm, change in expected.items():
        cfg = configs.ARMS[arm]
        for f in dataclasses.fields(v5):
            if f.name != "name":
                assert getattr(cfg, f.name) == getattr(v5, f.name), (arm, f.name)
        assert {k: getattr(cfg, k) for k in defaults} == defaults | change
    assert configs.C_MAIN == 1.2 and configs.C_SENSITIVITY == 1.3
    assert all(getattr(c, "hp_c", 0.0) != 1.5 for c in configs.ARMS.values())  # not used
    assert "Oracle" not in configs.DEPLOYABLE
    assert not any(getattr(configs.ARMS[a], "oracle_pose", False) for a in configs.DEPLOYABLE)


def test_dev_jobs_follow_the_protocol():
    jobs = dev.jobs()
    assert len(jobs) == 2 * 6 * 3 + 2 * 2 + 2 * 2
    assert {j[0] for j in jobs} == set(dev.NAMESPACES) <= set(v3e.DEV_NAMESPACES)
    assert jobs[0][1] == "D3xP0"  # the primary condition runs first
    assert {j[1] for j in jobs if j[2] == "Bfloor"} == {"D0xP0", "D3xP0"}
    assert {j[1] for j in jobs if j[2] == "Oracle"} == {"D3xP0", "D3xL1"}
    for ns, _cond, arm, job in jobs:
        assert job[0] == ns and job[3] is configs.ARMS[arm]
        assert job[4] is True and job[5] == frozen_v5.TIE_BREAK  # zone gating, rule-nbv-v2
    prior = {j[1]: j[3][6] for j in jobs}
    assert prior["D1xL2:L1"] == "L1" and prior["D3xP0"] is None


def test_cost_ratio_separates_a_wrong_localiser_from_an_ambiguous_fit(spec):
    from activeperception.nav.localize import map_outlines

    cfg = frozen_v5.GEOMETRY
    vp = spec.candidate_viewpoints[0]
    depth = _render(spec, vp.pose)
    outlines = map_outlines(spec)
    # localiser exact, the fit moved 4 cm: the localiser explains the depth at least as well
    at_truth = SimpleNamespace(dx=0.04, dy=0.0, dyaw=0.0, scale=1.0)
    r = hp.cost_ratio(depth, spec.camera, vp.pose, spec.zone, outlines, cfg, at_truth)
    assert r is not None and r < 1.0
    # localiser 20 cm off, the fit moved back to the truth: the localiser explains it far worse
    off = dataclasses.replace(vp.pose, x=vp.pose.x + 0.20)
    back = SimpleNamespace(dx=-0.20, dy=0.0, dyaw=0.0, scale=1.0)
    r = hp.cost_ratio(depth, spec.camera, off, spec.zone, outlines, cfg, back)
    assert r is not None and r > 5.0
    assert not hp.trusts_localiser(r, configs.C_SENSITIVITY)
    empty = np.full_like(depth, np.inf)  # no points: cannot be computed -> stays blind
    assert hp.cost_ratio(empty, spec.camera, vp.pose, spec.zone, outlines, cfg, back) is None


class _Base:
    """A replay world on synthetic depth with no detections."""

    def __init__(self, spec):
        views = (spec.initial_viewpoint, *spec.candidate_viewpoints)
        self.depth = {v.id: _render(spec, v.pose) for v in views}
        self.detections = SimpleNamespace(get=lambda eid, vid: [])

    def zone_visible_fraction(self, spec, viewpoint):
        return 1.0

    def _frames(self, spec):
        return SimpleNamespace(depth=self.depth.__getitem__)


def _conflict_world(monkeypatch, spec, arm, pose_level, ratio):
    """V3World for ``arm`` whose refinement always conflicts and whose cost ratio is ``ratio``."""
    from activeperception.v4 import geometry as g4
    from activeperception.v4.geometry import RefinementV4

    seen = {}

    def refine(depth, camera, est, zone, outlines, cfg, prior=None, **k):
        seen["prior"] = prior
        return RefinementV4(est, False, 0.05, 0.0, 0.0, 1.0, 1000, 100.0, math.inf, math.inf, True)

    monkeypatch.setattr(g4, "refine_pose_v4", refine)
    monkeypatch.setattr(hp, "cost_ratio", lambda *a, **k: ratio)
    world = v3e.V3World(_Base(spec), "D0", pose_level, configs.ARMS[arm], True)
    return world, seen


def _clearing_view(spec):
    from activeperception.v5.see import robust_visibility_v5

    for vp in spec.candidate_viewpoints:
        vis = robust_visibility_v5(
            _render(spec, vp.pose), spec.camera, vp.pose, spec.zone, 0.10, 0.06, 14
        )
        if sum(v >= 1.0 for v in vis) >= 3:
            return vp, vis
    raise AssertionError("no view clears a location")


def test_harness_blinds_trusts_or_uses_the_truth_per_arm(monkeypatch, spec):
    vp, fallback_vis = _clearing_view(spec)
    key = (spec.episode_id, vp.id)
    # B0: the conflict blinds the view, and v5's outputs keep their exact form
    world, seen = _conflict_world(monkeypatch, spec, "B0", "P0", 1.1)
    obs = world.observe(spec, vp)
    assert seen["prior"] == v3e.PRIOR_FLOOR
    assert not any(obs.location_visibility) and world.diag[key]["blind"]
    assert "hp_ratio" not in world.diag[key]
    # H-P, ratio <= c: the localiser's pose (exact under P0) with the failed-fit margin
    world, _ = _conflict_world(monkeypatch, spec, "HP12", "P0", 1.1)
    obs = world.observe(spec, vp)
    d = world.diag[key]
    assert tuple(obs.location_visibility) == tuple(fallback_vis)
    assert not d["blind"] and d["conflict"] and not d["refine_ok"]
    assert d["hp_trusted"] and d["hp_ratio"] == 1.1 and d["margin_xy"] == pytest.approx(0.10)
    # ratio above the main threshold, inside the sensitivity one
    world, _ = _conflict_world(monkeypatch, spec, "HP12", "P0", 1.25)
    assert not any(world.observe(spec, vp).location_visibility)
    assert world.diag[key]["blind"] and not world.diag[key]["hp_trusted"]
    world, _ = _conflict_world(monkeypatch, spec, "HP13", "P0", 1.25)
    assert any(world.observe(spec, vp).location_visibility)
    # B-floor: only the reported covariance changes
    world, seen = _conflict_world(monkeypatch, spec, "Bfloor", "P0", 1.1)
    world.observe(spec, vp)
    assert seen["prior"] == configs.FLOOR and world.diag[key]["blind"]
    # Oracle-pose (ceiling): the true pose even when the localiser is off, never blind
    world, _ = _conflict_world(monkeypatch, spec, "Oracle", "L2", 99.0)
    obs = world.observe(spec, vp)
    assert obs.viewpoint.pose == vp.pose and world.diag[key]["err_xy"] == 0.0
    assert not world.diag[key]["blind"] and any(obs.location_visibility)


def _summary(**k):
    base = {"FA": 0, "FP": 0, "GR": 0, "allview": 0, "occ": 0, "exceed": 5, "absent5": 0.8}
    return base | k


def _diff(mean=0.0, lo=-0.01, hi=0.02):
    cell = {"mean": mean, "ci95": [lo, hi], "arm_only": 0, "b0_only": 0}
    return {"rule@2": cell, "rule@3": cell, "rule@5": cell, "absent@5": cell}


def _verdict_inputs():
    from activeperception.v6 import devreport as dr

    summ, hpv, diffs = {}, {}, {}
    for ns, cond, arm in dr.expected_keys():
        summ[(ns, cond, arm)] = _summary()
        if arm in ("HP12", "HP13"):
            hpv[(ns, cond, arm)] = {"accepted_exceed_xy": 0}
        if arm != "B0":
            diffs[(ns, cond, arm)] = _diff()
    for ns in dev.NAMESPACES:
        diffs[(ns, "D3xP0", "HP12")] = _diff(0.15, 0.05, 0.25) | {
            "absent@5": {"mean": 0.15, "ci95": [0.05, 0.25], "arm_only": 9, "b0_only": 0}
        }
        summ[(ns, "D3xP0", "HP12")] = _summary(absent5=0.95)
        summ[(ns, "D3xP0", "Bfloor")] = _summary(absent5=0.85)
    return summ, hpv, diffs


def test_verdicts_follow_the_preregistered_rules():
    from activeperception.v6 import devreport as dr

    summ, hpv, diffs = _verdict_inputs()
    v = dr.verdicts(summ, hpv, diffs)
    assert v["recommend_formal"] and not v["stop"]
    # any safety count on HP-1.2 stops
    s = dict(summ) | {("v3-dev-dx", "D1xL1", "HP12"): _summary(occ=1)}
    assert dr.verdicts(s, hpv, diffs)["stop"]
    # an accepted view beyond its margin stops (HP-1.3 alone does not decide)
    h = dict(hpv) | {("v3-dev", "D1xL2:L1", "HP12"): {"accepted_exceed_xy": 1}}
    assert dr.verdicts(summ, h, diffs)["stop"]
    h = dict(hpv) | {("v3-dev", "D1xL2:L1", "HP13"): {"accepted_exceed_xy": 1}}
    assert not dr.verdicts(summ, h, diffs)["stop"]
    # gain below +0.10 on v3-dev D3xP0 stops
    d = dict(diffs) | {("v3-dev", "D3xP0", "HP12"): _diff(0.05) | {"absent@5": {
        "mean": 0.0999, "ci95": [0.0, 0.2], "arm_only": 6, "b0_only": 0}}}  # fmt: skip
    assert dr.verdicts(summ, hpv, d)["stop"]
    # a significant loss anywhere stops
    d = dict(diffs) | {("v3-dev", "D2xL2", "HP12"): _diff(-0.05, -0.09, -0.01)}
    v = dr.verdicts(summ, hpv, d)
    assert v["stop"] and v["R1_no_significant_loss"]["violations"]
    # B-floor safe and as good on both namespaces -> no recommendation for H-P alone
    s = dict(summ) | {(ns, "D3xP0", "Bfloor"): _summary(absent5=0.95) for ns in dev.NAMESPACES}
    v = dr.verdicts(s, hpv, diffs)
    assert v["F1_bfloor_as_good"]["holds"] and not v["recommend_formal"] and not v["stop"]
    # ... unless it exceeds its margins more often than B0
    s[("v3-dev", "D3xP0", "Bfloor")] = _summary(absent5=0.95, exceed=6)
    assert not dr.verdicts(s, hpv, diffs)["F1_bfloor_as_good"]["holds"]


def test_hp_views_counts_the_accepted_and_their_margin():
    from activeperception.v6 import devreport as dr

    def view(ratio, trusted, err, margin=0.10):
        return {"hp_ratio": ratio, "hp_trusted": trusted, "err_xy": err, "margin_xy": margin,
                "err_yaw": 0.0, "margin_yaw": 0.06}  # fmt: skip

    assert dr.hp_views({"views": [{"err_xy": 0.0}]}) is None  # not an H-P run
    v = [view(None, False, 0.0), view(1.1, True, 0.02), view(1.15, True, 0.12)]
    v.append(view(3.0, False, 0.3))
    h = dr.hp_views({"views": v})
    assert (h["evaluated"], h["accepted"], h["accepted_exceed_xy"]) == (3, 2, 1)
    assert h["accepted_err_xy_max"] == 0.12 and h["exceed_rate_upper95"] == 1.5


def test_failure_attribution_order():
    from activeperception.v6 import devreport as dr

    def r(path, by_path, by_all):
        return {"path": path, "cleared_by_path": by_path, "cleared_by_all_views": by_all}

    ok = {"status": "ok", "c_block": 0.0}
    blind = {"status": "blind", "c_block": 0.0}
    assert dr.attribute(r([ok, {"status": "ok", "c_block": 0.5}], 1.0, 1.0)).startswith("detection")
    assert dr.attribute(r([ok, blind], 0.9, 1.0)) == "path: blind views (ratio > c)"
    assert dr.attribute(r([ok, ok], 0.9, 1.0)) == "path: view selection / budget"
    assert dr.attribute(r([ok, blind], 0.9, 0.95)) == "not clearable with every view"
