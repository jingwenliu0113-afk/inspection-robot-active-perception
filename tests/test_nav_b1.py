"""Advanced B1 (decision 017): closed-loop bookkeeping and the Nav2-vs-teleport comparison."""

import json

import numpy as np

from activeperception.nav import b1_analysis as B
from activeperception.nav import b1_driver, scene
from activeperception.types import EpisodeGroundTruth, GroundTruthState, Split


def test_outcome_flags():
    o = B._outcome("absent", True, 1.0, 2)
    assert o["false_absent"] and o["geometric_risk"] and not o["correct"]
    o = B._outcome("present", False, 0.4, 3)
    assert o["false_present"] and not o["geometric_risk"]
    o = B._outcome("inconclusive", True, 0.9, 5)
    assert o["inconclusive"] and not o["false_absent"] and o["views"] == 5


def _gt(spec, state):
    return EpisodeGroundTruth(
        episode_id=spec.episode_id,
        object_present=spec.layout.object_present,
        state=state,
        revealable=True,
        visibility_initial=0.0,
        visibility_by_viewpoint={},
        zone_visible_by_viewpoint={},
        labeling_version="t",
    )


def test_nav_outcomes_use_decision_prefixes(tmp_path):
    spec = scene.nav_specs("nav-test", 1, variants=(0,))[0]
    run_dir = tmp_path / spec.episode_id / "rule-s0"
    run_dir.mkdir(parents=True)
    np.save(run_dir / "trace_01.npy", np.array([[0.0, 2.0, 0.0, 0.0], [1.0, 2.0, 1.0, 0.0]]))
    g = spec.candidate_viewpoints[0].pose
    gt = {"x": g.x, "y": g.y, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": g.yaw}
    steps = [
        {"decision": "inconclusive", "cleared_fraction": 0.0, "nav": None},
        {
            "decision": "present",
            "cleared_fraction": 0.9,
            "nav": {
                "goal": {"x": g.x, "y": g.y, "yaw": g.yaw},
                "result": "SUCCEEDED",
                "timed_out": False,
                "wall_timeout": False,
                "sim_s": 10.0,
                "trace_file": "trace_01.npy",
                "relocalize": {"corrections": 1, "steps": []},
            },
            "scoring": {"gt_base": gt},
            "observation": {"refine_ok": True},
        },
    ]
    (run_dir / "run.json").write_text(json.dumps({"steps": steps}))
    out, navs, missing = B.nav_outcomes(tmp_path, [spec])
    assert out[("rule", 0, 1, spec.episode_id)]["decision"] == "inconclusive"
    for b in (2, 3, 5):  # the run stopped at a definitive answer: later budgets keep it
        assert out[("rule", 0, b, spec.episode_id)]["correct"]
        assert out[("rule", 0, b, spec.episode_id)]["views"] == 2
    assert len(navs) == 1 and navs[0]["path_m"] == 1.0 and navs[0]["arrival_xy_m"] == 0.0
    assert {m["job"] for m in missing} == {
        "single-s0",
        "oracle-s0",
        "random-s0",
        "random-s1",
        "random-s2",
    }


def test_summary_and_pairing():
    specs = scene.nav_specs("nav-test", 1, variants=(0, 1))
    gts = {
        specs[0].episode_id: _gt(specs[0], GroundTruthState.UNOBSERVABLE),
        specs[1].episode_id: _gt(specs[1], GroundTruthState.ABSENT),
    }
    nav = {
        ("rule", 0, 2, specs[0].episode_id): B._outcome("present", True, 0.8, 2),
        ("rule", 0, 2, specs[1].episode_id): B._outcome("inconclusive", False, 0.9, 2),
    }
    tel = {
        ("rule", 0, 2, specs[0].episode_id): B._outcome("inconclusive", True, 0.5, 2),
        ("rule", 0, 2, specs[1].episode_id): B._outcome("absent", False, 1.0, 2),
    }
    s = B.summarize(nav, specs, gts)["rule@2"]
    assert s["accuracy"] == 0.5 and s["accuracy_by_state"] == {"absent": 0.0, "unobservable": 1.0}
    p = B.paired(nav, tel)["rule@2"]
    assert p == {
        "n": 2,
        "nav_minus_teleport_accuracy": 0.0,
        "nav_only_correct": 1,
        "teleport_only_correct": 1,
    }


def test_gen_nav_v1_specs_and_methods():
    specs = scene.nav_specs("nav-b1", 4)
    assert len(specs) == 16 and {s.generator_version for s in specs} == {"gen-nav-v1"}
    assert {s.split for s in specs} == {Split.NAV_DEV}
    assert [s.variant for s in specs[:4]] == [0, 1, 2, 3]
    assert b1_driver.METHODS == ("single", "random", "rule", "oracle")


def test_cluster_bootstrap_is_seeded_and_clustered():
    v = np.array([1.0, 1.0, 0.0, 0.0])
    g = np.array([0, 0, 1, 1])
    a = B.cluster_bootstrap(v, g, 200, 0)
    assert a == B.cluster_bootstrap(v, g, 200, 0)
    assert a["mean"] == 0.5 and a["ci95"][0] == 0.0 and a["ci95"][1] == 1.0


def test_b2_namespace_is_the_formal_split():
    assert {s.split for s in scene.nav_specs(scene.B2_NAMESPACE, 2)} == {Split.NAV_EVAL}
    assert {s.split for s in scene.nav_specs(scene.B1_NAMESPACE, 2)} == {Split.NAV_DEV}
