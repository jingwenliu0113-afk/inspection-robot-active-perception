"""Detector-selection metrics and the pre-registered rule (decision 005)."""

import numpy as np
import pytest

from activeperception.detector.evaluate import (
    FrameGT,
    auroc,
    average_precision,
    fpr_threshold,
    frame_ground_truth,
    frame_metrics,
    iou,
    select,
)


def test_auroc_known_values():
    assert auroc(np.array([0.9, 0.8]), np.array([0.1, 0.2])) == 1.0
    assert auroc(np.array([0.1]), np.array([0.9])) == 0.0
    assert auroc(np.array([0.5, 0.5]), np.array([0.5])) == 0.5
    # 3 pos, 2 neg: pairs won = (0.9>0.4,0.9>0.6, 0.7>0.4,0.7>0.6, 0.5>0.4) = 5 of 6
    assert auroc(np.array([0.9, 0.7, 0.5]), np.array([0.4, 0.6])) == pytest.approx(5 / 6)
    assert auroc(np.array([]), np.array([0.1])) is None


def test_fpr_threshold_controls_false_alarms():
    neg = np.linspace(0.0, 0.99, 100)
    t = fpr_threshold(neg, 0.05)
    assert (neg > t).mean() <= 0.05
    assert (neg >= t).mean() > 0.05  # the next lower threshold would exceed the budget
    assert fpr_threshold(np.zeros(50), 0.05) == 0.0


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0


def _gt(eid, present, vf=1.0, px=1000, box=(0, 0, 10, 10), group=0, vis=1.0):
    return FrameGT(
        eid,
        0,
        group,
        present,
        vis if present else 0.0,
        vf if present else 0.0,
        px if present else 0,
        box if present else None,
    )


def test_average_precision_hand_computed():
    rows = [_gt("a", True), _gt("b", True), _gt("n", False)]
    dets = {
        ("a", 0): [[0.9, 0, 0, 10, 10]],
        ("n", 0): [[0.8, 0, 0, 10, 10]],  # false alarm on an absent frame
        ("b", 0): [[0.7, 1, 0, 10, 10]],
    }
    # P/R: (1, .5), (.5, .5), (2/3, 1) -> envelope AP = .5 * 1 + .5 * 2/3
    assert average_precision(rows, dets) == pytest.approx(0.5 + 0.5 * 2 / 3)
    # a mislocalised box is a false positive, the frame stays a missed GT
    dets[("b", 0)] = [[0.7, 50, 50, 60, 60]]
    assert average_precision(rows, dets) == pytest.approx(0.5)
    # frames below the visibility / pixel floor are excluded from AP entirely
    rows2 = [_gt("a", True), _gt("t", True, vf=0.05)]
    dets2 = {("a", 0): [[0.9, 0, 0, 10, 10]], ("t", 0): []}
    assert average_precision(rows2, dets2) == 1.0


def test_frame_metrics_bins_and_s1():
    rows = [
        _gt("v", True, vf=0.9),
        _gt("p", True, vf=0.4, vis=0.4),
        _gt("q", True, vf=0.6),
        *[_gt(f"n{i}", False) for i in range(20)],
    ]
    dets = {(r.episode_id, 0): [] for r in rows}
    dets[("v", 0)] = [[0.95, 0, 0, 10, 10]]
    dets[("p", 0)] = [[0.40, 0, 0, 10, 10]]
    dets[("q", 0)] = [[0.05, 0, 0, 10, 10]]
    dets[("n0", 0)] = [[0.2, 0, 0, 10, 10]]
    dets[("n1", 0)] = [[0.1, 0, 0, 10, 10]]
    m = frame_metrics(rows, dets)
    assert m["P_auroc"] == pytest.approx(
        auroc(np.array([0.95, 0.05]), np.array([0.2, 0.1] + [0.0] * 18))
    )
    # two false alarms out of 20: only conf > 0.1 keeps the absent false-alarm rate at 5 %
    assert m["tau_fpr5"] == 0.1
    assert m["absent_fp_rate_at_tau_fpr5"] == 0.05
    by = {tuple(b["vis_fraction"]): b for b in m["bins"]}
    assert by[(0.25, 0.5)]["recall_at_tau_fpr5"] == 1.0
    assert by[(0.5, 0.75)]["recall_at_tau_fpr5"] == 0.0
    assert m["S1_occlusion_recall"] == 0.5


def _res(p, s1, lic):
    return {"P_auroc": p, "S1_occlusion_recall": s1, "license": lic}


def test_selection_rule_branches():
    agpl, bsd = "AGPL-3.0", "BSD-3-Clause"
    clear = {"a": _res(0.95, 0.5, agpl), "b": _res(0.90, 0.9, bsd)}
    assert select(clear, {})[0] == "a"
    s1 = {"a": _res(0.95, 0.5, agpl), "b": _res(0.945, 0.7, bsd)}
    assert select(s1, {})[0] == "b"
    lic = {"a": _res(0.95, 0.70, agpl), "b": _res(0.945, 0.69, bsd)}
    assert select(lic, {})[0] == "b"
    cpu = {"a": _res(0.95, 0.70, agpl), "b": _res(0.945, 0.69, agpl)}
    assert select(cpu, {"a": 90.0, "b": 40.0})[0] == "b"


def test_refuses_non_detsel_episode_sets(tmp_path):
    from activeperception.episodes import build_episode_set
    from activeperception.serialize import save_episode_set
    from activeperception.sim import SyntheticWorld

    specs = build_episode_set("core", 2)
    world = SyntheticWorld()
    path = tmp_path / "e.json"
    save_episode_set(path, specs, {s.episode_id: world.ground_truth(s) for s in specs}, "x")
    with pytest.raises(SystemExit):
        frame_ground_truth(path, tmp_path)
