"""v4 development configurations (decision 029). All start from the frozen v3 geometry (decision
025): margins 6 cm / 0.03 rad, localiser-prior gate k = 3, conflicting fits clear nothing."""

from __future__ import annotations

import dataclasses

from ..v3 import frozen_v3
from .geometry import GeometryConfigV4

_V3 = {f.name: getattr(frozen_v3.GEOMETRY, f.name) for f in dataclasses.fields(frozen_v3.GEOMETRY)}
BASE = GeometryConfigV4(**{**_V3, "name": "v4-as-v3"})  # identical behaviour to frozen v3

SCALES_WIDE = (0.96, 0.98, 1.0, 1.02, 1.04)

CONFIGS = {
    c.name: c
    for c in (
        BASE,
        dataclasses.replace(BASE, window_k=4.0, name="w4"),
        dataclasses.replace(BASE, window_k=5.0, name="w5"),
        dataclasses.replace(BASE, scales=SCALES_WIDE, name="s4"),
        dataclasses.replace(BASE, window_k=4.0, scales=SCALES_WIDE, name="w4s4"),
        # coarse-grid uniqueness: correct fits are rarely unique either (ratio 1.03-1.3) -> dropped
        dataclasses.replace(BASE, window_k=4.0, unique_ratio=1.5, name="w4u15"),
        # scale hypotheses: margin + their pose spread; hb*: blind beyond a spread
        dataclasses.replace(BASE, window_k=4.0, hyp_scales=SCALES_WIDE, name="w4h"),
        dataclasses.replace(
            BASE, window_k=4.0, hyp_scales=SCALES_WIDE, hyp_blind_m=0.10, name="w4hb10"
        ),
        dataclasses.replace(
            BASE,
            window_k=4.0,
            hyp_scales=SCALES_WIDE,
            hyp_margin=False,
            hyp_blind_m=0.04,
            name="w4hb4",
        ),
    )
}


def config(name: str) -> GeometryConfigV4:
    return CONFIGS[name]
