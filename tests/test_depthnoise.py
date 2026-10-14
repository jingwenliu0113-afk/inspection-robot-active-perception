"""B (decision 028): the statistics recover the parameters of a known error model."""

import numpy as np
import pytest

from activeperception.depthnoise import stats
from activeperception.r0b import DEPTH_LEVELS
from activeperception.r0b_noise import apply_depth_noise


def scene(h: int = 120, w: int = 320) -> np.ndarray:
    ref = np.tile(np.linspace(0.8, 4.8, w), (h, 1))  # range ramp across the image
    ref[40:80, 100:140] = 1.0  # a near box -> depth discontinuities
    return ref


@pytest.mark.parametrize("level", ["D1", "D2"])
def test_statistics_recover_the_model(level):
    dn = DEPTH_LEVELS[level]
    acc = stats.Accumulator(edge_px=dn.edge_px)
    rng = np.random.default_rng(0)
    for i in range(12):
        ref = scene()
        acc.add(apply_depth_noise(ref, dn, np.random.default_rng(i)), ref, rng)
    r = acc.result()
    assert r["fit"]["rel_at_2m"] == pytest.approx(dn.rel_at_2m, rel=0.2)
    assert r["fit"]["p"] == pytest.approx(2.0, abs=0.3)
    bias = np.median([b["scale_bias"] for b in r["bins"]])
    assert bias == pytest.approx(dn.bias, abs=0.002)
    invalid = np.median([b["invalid"] for b in r["bins"]])
    assert invalid == pytest.approx(dn.dropout, abs=0.01)
    assert r["edges"]["missing"] == pytest.approx(0.5, abs=0.1)
    assert r["corr_px"] == pytest.approx(2 * dn.corr_px, rel=0.3)  # 1/e lag of a Gaussian blur


def test_clean_depth_has_no_error():
    acc = stats.Accumulator()
    ref = scene()
    acc.add(ref.copy(), ref, np.random.default_rng(0))
    r = acc.result()
    assert all(b["invalid"] == 0 and abs(b["scale_bias"]) < 1e-9 for b in r["bins"])
    assert r["edges"]["missing"] == 0 and r["edges"]["flying"] == 0
