"""decision 036: E0 metrics, the confirm-present rule (off by default) and the E1 spec."""

import math

import pytest

from activeperception.inzone import confirm, e1spec
from activeperception.inzone import metrics as m


def test_bands_and_h2_ceiling():
    conf = [0.1, 0.75, 0.85, 0.93, 0.97, 0.985, 0.995, 1.0]
    b = m.bands(conf)
    assert b["<0.7"] == 1 and sum(b.values()) == len(conf)
    assert b["[0.99, 1.0]"] == 2  # the top band includes 1.0
    c = m.h2_ceiling(conf, 0.7, 0.98)
    assert c["fp"] == 7 and c["fp_at_or_above_tau_hi"] == 3
    assert c["max_relative_reduction"] == pytest.approx(4 / 7)
    assert m.h2_ceiling([0.1], 0.7, 0.98)["share_unremovable"] is None
    r = m.recall_exposure([0.6, 0.8, 0.99], 0.7, 0.98)
    assert r == {"detected": 2, "needs_confirmation": 1, "share": 0.5}


def test_pair_consistency_respects_separation():
    az = [math.radians(a) for a in (0, 30, 90, 180)]
    # views 0 and 1 are 30 deg apart: not a pair
    assert m.pair_counts([0.9, 0.9, 0.1, 0.1], az, 0.7, math.radians(45)) == (4, 0)
    assert m.pair_counts([0.9, 0.1, 0.9, 0.1], az, 0.7, math.radians(45)) == (5, 2)
    assert m.angular_sep(math.radians(350), math.radians(10)) == pytest.approx(math.radians(20))
    pc = m.pair_consistency([([0.9, 0.9], [0.0, math.pi]), ([0.9, 0.2], [0.0, math.pi])], 0.7, 1.0)
    assert pc["p"] == pytest.approx(2 / 3)


def test_exposure_and_bootstrap():
    e = m.exposure(0.05, 3)
    assert e["independent"] == pytest.approx(1 - 0.95**3) and e["fully_correlated"] == 0.05
    ci = m.cluster_bootstrap_ratio([1, 2, 3, 4], [2, 2, 4, 4], n_boot=500)
    assert ci[0] <= 10 / 12 <= ci[1]
    assert m.cluster_bootstrap_ratio([1], [1]) is None


def test_spread_and_summary():
    d = m.spread([(0, 0), (0.1, 0), (0, 0.3)])
    assert sorted(round(x, 3) for x in d) == [0.1, 0.3, round(math.hypot(0.1, 0.3), 3)]
    s = m.summarize_distances(d)
    assert s["n"] == 3 and s["share_le_0.25"] == pytest.approx(1 / 3)
    assert m.summarize_distances([]) == {"n": 0}


def test_confirm_present_rule():
    p = confirm.ConfirmParams(tau=0.7, tau_hi=0.98, r=0.25)
    assert confirm.confirm_present([[(0.99, 0.0, 0.0)]], p) == (True, 0.99)  # single, high
    assert confirm.confirm_present([[(0.9, 0.0, 0.0)]], p)[0] is False  # needs confirmation
    two = [[(0.9, 0.0, 0.0)], [(0.8, 0.1, 0.1)]]
    assert confirm.confirm_present(two, p) == (True, 0.8)
    far = [[(0.9, 0.0, 0.0)], [(0.8, 0.5, 0.0)]]  # same confidence, different places
    assert confirm.confirm_present(far, p)[0] is False
    same_view = [[(0.9, 0.0, 0.0), (0.8, 0.05, 0.0)]]  # two boxes in one view do not confirm
    assert confirm.confirm_present(same_view, p)[0] is False
    assert confirm.confirm_present([], p) == (False, 0.0)


def _rows(n_obj: dict[str, int], views: int = 8):
    rows = []
    for cat, n in n_obj.items():
        for k in range(n):
            for v in range(views):
                rows.append({
                    "object_id": f"{cat}-{k}", "category": cat, "file": f"{cat}-{k}-{v}.jpg",
                    "azimuth_deg": str(v * 360 / views), "distance_m": "2.0",
                    "camera_height_m": "1.1", "notes": "",
                })  # fmt: skip
    return rows


def test_e1_spec_validator():
    ok = _rows({"hydrant": 8, "valve-pipe": 8, "bin": 4, "bollard-post": 4})
    assert e1spec.validate(ok) == []
    s = e1spec.summary(ok)
    assert s["objects"] == 24 and s["photos"] == 192
    assert set(s["by_split"]) == {"dev", "test"}
    few = _rows({"hydrant": 8, "valve-pipe": 8, "bin": 8}, views=5)
    assert any("views" in b or "gap" in b for b in e1spec.validate(few))
    bad = _rows({"hydrant": 8, "valve-pipe": 8, "bin": 8})
    bad[0]["category"] = "statue"
    bad[1]["distance_m"] = "9"
    probs = e1spec.validate(bad)
    assert any("unknown category" in p for p in probs) and any("distance" in p for p in probs)
    assert e1spec.validate(_rows({"hydrant": 3}))  # too few objects per group
    assert e1spec.split_of("hydrant-0") == e1spec.split_of("hydrant-0")


def test_e1_manifest_from_file_names():
    names = [f"h{k}__hydrant__{a}.jpg" for k in range(8) for a in range(0, 360, 45)]
    names += [f"v{k}__valve-pipe__{a}.jpg" for k in range(8) for a in range(0, 360, 45)]
    names += [f"b{k}__bin__{a}.jpg" for k in range(8) for a in range(0, 360, 45)]
    rows = e1spec.manifest_from_names(names)
    assert e1spec.validate(rows) == []
    bad = e1spec.manifest_from_names(["oops.jpg"] + names)
    assert any("unknown category" in p or "numbers" in p for p in e1spec.validate(bad))
