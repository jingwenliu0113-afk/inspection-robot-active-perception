"""R0b (decision 022): conditions, scoring-only occupied locations, the safety verdicts."""

import dataclasses

import numpy as np

from activeperception import r0b
from activeperception.serialize import load_spec_set


def spec(present: bool):
    for s in load_spec_set("data/episodes/specs-nav-b1.json")[0]:
        if s.layout.object_present == present:
            return s
    raise AssertionError


def test_eighteen_conditions_and_the_frozen_levels():
    assert len(r0b.conditions()) == 18
    d1, l1 = r0b.DEPTH_LEVELS["D1"], r0b.POSE_LEVELS["L1"]
    assert (d1.rel_at_2m, d1.bias, d1.edge_px, d1.dropout) == (0.01, 0.01, 2, 0.01)
    assert (l1.sigma_xy, l1.sigma_yaw, l1.sigma_z, l1.sigma_pitch) == (0.03, 0.02, 0.01, 0.005)
    assert r0b.PRIMARY == ("D1", "L1", "b") and r0b.STRESS == ("D2", "L2", "b")


def test_occupied_locations_are_under_the_object_only():
    s = spec(True)
    occ = r0b.occupied_locations(s)
    assert occ.any() and not occ.all()
    assert not r0b.occupied_locations(spec(False)).any()
    far = dataclasses.replace(
        s.layout, object_pose=dataclasses.replace(s.layout.object_pose, x=s.zone.cx + 5.0)
    )
    assert not r0b.occupied_locations(dataclasses.replace(s, layout=far)).any()


def _res(depth, pose, pipe, fa=0, gr=0, all_views=()):
    cell = {"false_absent": fa, "geometric_risk": gr, "accuracy": 1.0}
    return {
        "condition": {"depth": depth, "pose": pose, "pipeline": pipe},
        "summary": {"rule@2": cell, "random@2": dict(cell, false_absent=0, geometric_risk=0)},
        "all_views_geometric_risk": list(all_views),
        "occupied_false_clearance": {"views": 0, "present_views": 10},
    }


def test_safety_needs_every_count_at_zero():
    assert r0b.safe(_res("D1", "L1", "b"))
    assert not r0b.safe(_res("D1", "L1", "b", fa=1))
    assert not r0b.safe(_res("D1", "L1", "b", gr=1))
    assert not r0b.safe(_res("D1", "L1", "b", all_views=["e"]))


def test_criteria_pick_the_preregistered_conditions():
    results = [_res(*c) for c in r0b.conditions()]
    stressed = _res("D2", "L2", "b", fa=2)
    results = [stressed if tuple(r["condition"].values()) == r0b.STRESS else r for r in results]
    c = r0b.criteria(results)
    assert c["R1_primary_D1_L1_b"]["pass"] and not c["R2_stress_D2_L2_b"]["pass"]
    assert c["pipeline_b_safe"]["D2xL2"] is False and c["R3_pipeline_a_safe"]["D2xL2"] is True
    md = r0b.markdown({"results": results, "criteria": c})
    assert "R1（主要" in md and "**不安全**" in md
    assert np.isfinite(len(md))
