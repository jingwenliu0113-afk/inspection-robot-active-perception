"""decision 037: the D3xP0 diagnosis bookkeeping (synthetic records)."""

from activeperception.d3p0 import summarize as sm


def _view(vp, status, t0, t1, t2, t3, c1=None, est_err=0.0, ratio=1.1):
    v = {
        "vp": vp, "status": status, "T0": t0, "T1": t1, "T2": t2, "T3": t3,
        "est_err": est_err, "fit_err": 0.05, "move": 0.04, "move_along_axis": 0.9,
        "costs": {"ratio": ratio}, "C1_margin_xy": 0.06,
    }  # fmt: skip
    if c1 is not None:
        v["C1"] = c1
    return v


def _ep(eid, views, decision, path=(-1, 0)):
    return {"episode": eid, "state": "absent", "views": views,
            "rule_b5": {"views": list(path), "decision": decision}}  # fmt: skip


def test_cleared_union_and_blind_substitution():
    v = [_view(-1, "ok", [1, 0], [1, 0], [1, 0], [1, 0]),
         _view(0, "blind", [0, 1], [0, 1], [0, 1], [0, 0], c1=[0, 1])]  # fmt: skip
    assert sm.cleared(v, "T3").tolist() == [True, False]
    assert sm.cleared(v, "T3", blind_as="C1").tolist() == [True, True]
    assert sm.cleared(v, "T0", ids={-1}).tolist() == [True, False]


def test_failure_categories_follow_the_protocol_order():
    ones, zeros = [1, 1], [0, 0]
    half = [1, 0]
    rows = [
        _ep("structural", [_view(-1, "ok", half, half, half, half)], "inconclusive"),
        _ep("noise", [_view(-1, "ok", ones, half, half, half)], "inconclusive"),
        _ep("margin", [_view(-1, "ok", ones, ones, half, half)], "inconclusive"),
        _ep("loc", [_view(-1, "blind", ones, ones, ones, zeros, c1=ones)], "inconclusive"),
        _ep(
            "selection",
            [
                _view(-1, "ok", half, half, half, half),
                _view(5, "ok", [0, 1], [0, 1], [0, 1], [0, 1]),
            ],
            "inconclusive",
        ),  # fmt: skip
        _ep("decided", [_view(-1, "ok", ones, ones, ones, ones)], "absent"),
    ]
    d = sm.decomposition(rows)
    assert d["failure_categories"] == {
        "structural": 1, "depth-noise": 1, "margin": 1, "localisation-handling": 1,
        "selection-or-budget": 1,
    }  # fmt: skip
    assert d["rule_b5_absent"] == 1 and d["fully_cleared_13_views"]["T3"] == 2
    assert d["failures"]["loc"]["b5_path_cleared_with_C1"] is True


def test_discriminator_counts_localiser_errors():
    rows = [{"views": [
        _view(0, "blind", [1], [1], [1], [0], c1=[1], est_err=0.0, ratio=1.02),
        _view(1, "blind", [1], [1], [1], [0], c1=[1], est_err=0.15, ratio=1.8),
    ]}]  # fmt: skip
    d = sm.discriminator({"X": rows})["X"]
    assert d["localiser_wrong_beyond_C1_margin"] == 1
    assert d["accepted_if_ratio_le"]["1.05"] == {"accepted": 1, "accepted_with_localiser_wrong": 0}
    assert d["accepted_if_ratio_le"]["1.5"]["accepted_with_localiser_wrong"] == 0
