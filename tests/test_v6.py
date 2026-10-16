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
