"""Frozen v5 (decision 034) = frozen v4 + see-v5. v1-v4 stay unchanged in their own modules.

Chosen on development data only (decision 033 + appendix A, docs/v5-development.md). Changing
anything here after the formal run means a v6, a new decision log and new data.
"""

from __future__ import annotations

from ..v4 import frozen_v4
from . import configs

CONFIG_NAME = "v5"
SEE_K = 14  # majority of the 27-pose set; not tuned
# see-v5 on frozen v4 (dev, v3-dev / v3-dev-dx, 9 condition sets): all safety counts 0; Rule b3
# D2xL2 0.767 -> 0.950, D3xL1 0.758 -> 0.875; absent@5 D3xL1 0.767 -> 0.950. The depth-scale
# self-calibration (decision 033) is not used: narrowing the hypothesis band traded the safety
# proxy for absent, and calibrated depth for the see-through changed nothing.
GEOMETRY = configs.with_see(frozen_v4.GEOMETRY, SEE_K, name=CONFIG_NAME, see_bracket=True)
FREE = configs.with_see(frozen_v4.GEOMETRY, SEE_K, name="v5-free", see_bracket=False)  # R2 only
TIE_BREAK = frozen_v4.TIE_BREAK  # rule-nbv-v2 unchanged
X2_CONDITIONS = (("D2", "L2"), ("D3", "L1"))
X2_BUDGET = 3


def describe() -> dict:
    d = frozen_v4.describe()
    d["see_v5"] = {
        "k": GEOMETRY.see_k,
        "bracket": GEOMETRY.see_bracket,
        "veto": "any pose blocked or outside the image",
        "missing": "fewer than 40 % valid pixels in the 5 x 5 neighbourhood",
    }
    return d
