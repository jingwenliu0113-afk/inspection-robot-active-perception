"""Frozen v4 (decision 031). v1 / v2 / v3 / decision 016 stay unchanged in their own modules.

Chosen on development data only (decision 029, docs/v4-development.md). Changing anything here
after the formal run means a v5, a new decision log and new data.
"""

from __future__ import annotations

import dataclasses

from ..v3 import frozen_v3
from . import configs
from . import geometry as g

CONFIG_NAME = "v4"
# w4hj on v3-dev: the margin exceedance of trusted fits fell from 65 / 144 (v3, D2xL2 / D3xL1) to
# 11 / 5 with the largest excess 8.1 / 2.7 cm (v3: 14.0 / 7.6); absent@5 0.900 / 0.767 (v3:
# 0.933 / 0.817). The scale-edge rule (w4hje) removed a few more but cost D3xL1 absent@5 0.767 ->
# 0.667; the blind-on-spread rule (hb10) cost more again -> neither is used.
# + decision-v4 gating (g8): on v3-dev-dx D3xL1 both v3 and w4hj called one absent episode present
# (a distractor 1.0 m away, its box depth 6.3 % short); with the +-8 % band: 0. No change where
# there is no distractor; v3-dev-dx D0xP0 absent@5 1.000 -> 0.983.
GEOMETRY = dataclasses.replace(configs.CONFIGS["w4hjg8"], name=CONFIG_NAME)
TIE_BREAK = frozen_v3.TIE_BREAK  # rule-nbv-v2 unchanged
ABSENT_MIN = 0.90  # W2, as V2 of decision 025
EXCEED_MAX_RATIO = 0.25  # W5: v4's exceedance <= this share of v3's on the same data


def describe() -> dict:
    d = frozen_v3.describe()
    d["nav_pose_v4"] = {
        "window": f"max({g.SEARCH_XY_M} m, {GEOMETRY.window_k} sigma) / max({g.SEARCH_YAW} rad, "
        f"{GEOMETRY.window_k} sigma)",
        "scale_hypotheses": list(GEOMETRY.hyp_scales),
        "hypothesis_ratio": GEOMETRY.hyp_ratio,
        "hypothesis_coarse_points": GEOMETRY.hyp_points,
        "scale_jacobian": GEOMETRY.scale_jacobian,
        "scale_edge": GEOMETRY.scale_edge,
        "margin_ok": f"{list(GEOMETRY.margin_ok)} + hypothesis spread",
        "blind_on_spread_m": None if GEOMETRY.hyp_blind_m == float("inf") else GEOMETRY.hyp_blind_m,
    }
    d["zone_gating"]["depth_scale_band"] = GEOMETRY.gate_band  # decision-v4
    d["nav_pose_base"] = d.pop("nav_pose_v3")  # weights, range cut, eigenvalue, prior gate
    d["nav_pose_base"].pop("scales")  # replaced by the scale hypotheses
    d["nav_margin_v4"] = d.pop("nav_margin_v3")
    return d
