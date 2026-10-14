"""R0b noise models (decision 022): the depth and pose errors have the stated statistics."""

import numpy as np
import pytest

from activeperception import r0b_noise as rn
from activeperception.types import Pose

D = rn.DepthNoise(
    "t", rel_at_2m=0.02, bias=0.01, corr_px=3.0, edge_px=2, edge_jump_m=0.1, dropout=0.0
)


def test_streams_are_reproducible_and_independent():
    a = rn.rng_for("ep", 3, "D1").random(4)
    assert np.array_equal(a, rn.rng_for("ep", 3, "D1").random(4))
    assert not np.array_equal(a, rn.rng_for("ep", 4, "D1").random(4))


def test_correlated_field_has_unit_variance_and_is_smooth():
    f = rn.correlated_field((400, 400), 3.0, rn.rng_for("f"))
    assert f.std() == pytest.approx(1.0, abs=0.08)
    lag1 = np.corrcoef(f[:, :-1].ravel(), f[:, 1:].ravel())[0, 1]
    assert lag1 > 0.9  # neighbouring pixels move together (block matching)


def test_flat_depth_gets_the_bias_and_quadratic_sigma():
    for z in (1.0, 2.0, 4.0):
        depth = np.full((300, 300), z, np.float32)
        out = rn.apply_depth_noise(depth, D, rn.rng_for("flat", int(z)))
        err = out[20:-20, 20:-20] - z
        assert err.mean() == pytest.approx(D.bias * z, abs=0.25 * D.rel_at_2m * 2 * (z / 2) ** 2)
        assert err.std() == pytest.approx(D.rel_at_2m * 2 * (z / 2) ** 2, rel=0.15)


def test_edges_become_missing_or_flying_and_no_return_is_kept():
    depth = np.full((60, 80), 1.0, np.float32)
    depth[:, 40:] = 3.0
    depth[0, 0] = np.inf
    clean = rn.DepthNoise("e", 0.0, 0.0, 0.0, 2, 0.1, 0.0)
    out = rn.apply_depth_noise(depth, clean, rn.rng_for("edge"))
    band = out[5:-5, 38:42]
    assert np.isnan(band).any()
    fly = band[np.isfinite(band)]
    assert ((fly > 1.0) & (fly < 3.0)).any()  # between the near and the far side
    assert np.array_equal(out[5:-5, 10:30], depth[5:-5, 10:30])  # away from edges: unchanged
    assert np.isinf(out[0, 0])


def test_dropout_rate():
    n = rn.DepthNoise("d", 0.0, 0.0, 0.0, 0, 0.1, 0.05)
    out = rn.apply_depth_noise(np.full((200, 200), 2.0, np.float32), n, rn.rng_for("drop"))
    assert np.isnan(out).mean() == pytest.approx(0.05, abs=0.01)


def test_pose_noise_statistics():
    n = rn.PoseNoise("p", sigma_xy=0.03, sigma_yaw=0.02, sigma_z=0.01, sigma_pitch=0.005)
    p0 = Pose(1.0, 2.0, 1.1, 0.5, 0.3)
    ps = [rn.perturb_pose(p0, n, rn.rng_for("pose", i)) for i in range(4000)]
    for attr, s in (("x", 0.03), ("y", 0.03), ("yaw", 0.02), ("z", 0.01), ("pitch", 0.005)):
        v = np.array([getattr(p, attr) for p in ps]) - getattr(p0, attr)
        assert v.mean() == pytest.approx(0.0, abs=4 * s / np.sqrt(len(v)))
        assert v.std() == pytest.approx(s, rel=0.05)
