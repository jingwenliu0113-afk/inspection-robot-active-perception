"""v5 development components (decision 033): depth-scale self-calibration, hypothesis band,
shared noise functions, Mac heavy-lock guard."""

import math

import numpy as np
import pytest

from activeperception.depthnoise.d3 import apply_d3
from activeperception.r0b import DEPTH_LEVELS
from activeperception.r0b_noise import apply_depth_noise, rng_for
from activeperception.serialize import load_spec_set
from activeperception.v3 import eval as v3e
from activeperception.v5 import calib, configs, dev, maclock


@pytest.fixture(scope="module")
def spec():
    return load_spec_set("data/episodes/specs-nav-b1.json")[0][0]


def _clean():
    z = np.linspace(1.0, 4.0, 480 * 640).reshape(480, 640).astype(np.float32)
    z[:40, :] = np.inf  # no return
    z[200:260, 300:340] = 1.2  # a near step for the stereo band / edges
    return z


def test_noisy_depth_is_the_original_inline_noise(spec):
    clean = _clean()
    eid = spec.episode_id
    for level in ("D1", "D2"):
        ref = apply_depth_noise(clean, DEPTH_LEVELS[level], rng_for(eid, "v3", "depth", level))
        np.testing.assert_array_equal(v3e.noisy_depth(spec, 3, clean, level), ref)
    f = spec.camera.width / 2 / math.tan(spec.camera.hfov / 2)
    ref = apply_d3(clean, f, rng_for(eid, "v3", "depth", "D3"))
    np.testing.assert_array_equal(v3e.noisy_depth(spec, 3, clean, "D3"), ref)
    assert v3e.noisy_depth(spec, 3, clean, "D0") is clean


def test_repeat_frames_are_new_draws_and_drift_scales_the_camera(spec):
    clean = _clean()
    a = v3e.noisy_depth(spec, 3, clean, "D3")
    r0 = v3e.noisy_depth(spec, 3, clean, "D3", rep=0)
    r1 = v3e.noisy_depth(spec, 3, clean, "D3", rep=1)
    assert not np.array_equal(a, r0, equal_nan=True)
    assert not np.array_equal(r0, r1, equal_nan=True)
    np.testing.assert_array_equal(v3e.noisy_depth(spec, 3, clean, "D3", rep=1), r1)
    up = v3e.noisy_depth(spec, 3, clean, "D3up")
    np.testing.assert_allclose(up, a * 1.015, rtol=1e-6)


def test_estimated_pose_matches_the_world(spec):
    vp = spec.candidate_viewpoints[2]
    assert v3e.estimated_pose(spec, vp, "P0") == vp.pose
    e = v3e.estimated_pose(spec, vp, "L1")
    assert e != vp.pose and e == v3e.estimated_pose(spec, vp, "L1")


def test_pair_ratio_measures_a_relative_scale():
    a = _clean()
    assert calib.pair_ratio(a, a * 1.01) == pytest.approx(0.01, abs=1e-6)
    assert calib.pair_ratio(a, a) == 0.0
    tiny = np.full((10, 10), np.nan, np.float32)
    assert calib.pair_ratio(tiny, tiny) is None


def test_scale_and_jitter_estimators():
    fits = [{"ok": True, "scale": s} for s in (0.97, 0.975, 0.975, 0.98, 1.045)]
    fits += [{"ok": False, "scale": 1.045}] * 10  # untrusted fits never count
    est = calib.estimate_scale(fits)
    assert est["center"] == pytest.approx(0.975) and est["n_ok"] == 5
    assert calib.estimate_scale([{"ok": False, "scale": 1.0}])["center"] == 1.0
    rng = np.random.default_rng(0)
    j = 0.01
    ratios = list((j * rng.standard_normal(4000)) - (j * rng.standard_normal(4000)))
    assert calib.estimate_jitter(ratios)["sigma"] == pytest.approx(j, rel=0.08)
    assert math.isnan(calib.estimate_jitter([None, 0.01])["sigma"])


def test_band_rules_and_calibrated_hypotheses():
    assert configs.band_for("f0.02", math.nan) == 0.02
    assert configs.band_for("j2", 0.01) == pytest.approx(0.025)
    assert configs.band_for("j2", 0.0) == pytest.approx(0.01)  # floor + resolution
    assert configs.band_for("j2", math.nan) == pytest.approx(0.01)
    cfg = configs.calibrated(0.975, 0.02, name="t")
    assert cfg.hyp_scales == (0.955, 0.965, 0.975, 0.985, 0.995)
    # everything else is frozen v4
    for f in ("window_k", "scale_jacobian", "hyp_ratio", "gate_band", "prior_k", "margin_ok"):
        assert getattr(cfg, f) == getattr(configs.BASE, f)
    with pytest.raises(ValueError):
        configs.band_for("x1", 0.0)


def test_condition_parsing_and_true_scales():
    assert dev.parse("D3xL1") == {"depth": "D3", "pose": "L1", "prior": None, "cal_depth": "D3"}
    assert dev.parse("D1xL2:L1") == {"depth": "D1", "pose": "L2", "prior": "L1", "cal_depth": "D1"}
    assert dev.parse("D3upxL1@D3")["cal_depth"] == "D3"
    assert dev.true_scale("D3up") == pytest.approx(0.975 * 1.015)


def test_mac_lock_guard(tmp_path):
    lock = tmp_path / "lock"
    assert maclock.holder(lock) is None
    maclock.require_free(lock)
    lock.mkdir()
    (lock / "owner.txt").write_text("pid=1\ncwd=/x\n")
    assert maclock.holder(lock) == "pid=1; cwd=/x"
    with pytest.raises(SystemExit):
        maclock.require_free(lock)


def test_v5_runner_refuses_formal_and_same_namespace():
    with pytest.raises(SystemExit):
        dev.main(["--ns", "v4", "--cal-ns", "v3-dev-dx", "--out", "/tmp/x"])
    with pytest.raises(SystemExit):
        dev.main(["--ns", "v3-dev", "--cal-ns", "v3-dev", "--out", "/tmp/x"])


def test_calibrated_config_see_scale_and_v4_identity():
    from activeperception.v3.geometry import GeometryConfig
    from activeperception.v4.geometry import GeometryConfigV4

    cfg = configs.calibrated(0.975, 0.02, name="t", see=True)
    assert isinstance(cfg, GeometryConfigV4) and isinstance(cfg, GeometryConfig)
    assert cfg.see_scale == 0.975
    assert configs.calibrated(0.975, 0.02, name="t").see_scale == 1.0
    assert not hasattr(configs.BASE, "see_scale")  # frozen v4 reads raw depth
