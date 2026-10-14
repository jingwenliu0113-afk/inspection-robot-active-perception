"""decision 028 §4: the measured D435 / D455 numbers against the R0b D1 / D2 model, by the
comparison rules written before the analysis. Only 1-3 m (the inspection range).

    uv run python -m activeperception.depthnoise.compare results/depthnoise/planes.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..r0b import DEPTH_LEVELS

RANGE_M = (1.0, 3.0)
MODEL_CORR_1E_PX = 2 * DEPTH_LEVELS["D1"].corr_px  # 1/e lag of the Gaussian-blurred field


def model_sigma(level: str, z: float) -> float:
    dn = DEPTH_LEVELS[level]
    return dn.rel_at_2m * 2.0 * (z / 2.0) ** 2


def judge(rows: list[dict]) -> dict:
    rows = [r for r in rows if RANGE_M[0] - 1e-9 <= r["z_nominal_m"] <= RANGE_M[1] + 1e-9]
    d1 = all(r["spatial_sigma_m"] <= model_sigma("D1", r["z_nominal_m"]) for r in rows)
    d2 = all(r["spatial_sigma_m"] <= model_sigma("D2", r["z_nominal_m"]) for r in rows)
    worst_bias = max(rows, key=lambda r: abs(r["bias"]))
    signs = {"+" if r["bias"] > 0 else "-" for r in rows if abs(r["bias"]) > 0.005}
    corr = max(r["corr_1e_sim_px"]["x"] for r in rows)
    quant = all(r["quant_step_m"] <= r["spatial_sigma_m"] / 2 for r in rows)
    fixed = max(r["fixed_sigma_m"] / r["spatial_sigma_m"] for r in rows)
    return {
        "random_error": "D1 已涵蓋" if d1 else ("保守或相近（D2 涵蓋）" if d2 else "低估"),
        "bias": {
            "worst": worst_bias["bias"],
            "at_m": worst_bias["z_nominal_m"],
            "verdict": "保守或相近" if abs(worst_bias["bias"]) <= 0.02 else "低估",
            "sign": "符號未涵蓋（量到低估距離）" if "-" in signs else "與模型同向",
        },
        "dropout_roi": {
            "worst": max(r["invalid_roi"] for r in rows),
            "verdict": "保守或相近"
            if max(r["invalid_roi"] for r in rows) <= DEPTH_LEVELS["D2"].dropout
            else "低估",
        },
        "quantisation": "可忽略" if quant else "量化不可忽略",
        "correlation": {
            "worst_1e_sim_px": corr,
            "model_1e_sim_px": MODEL_CORR_1E_PX,
            "verdict": "保守或相近" if corr <= 2 * MODEL_CORR_1E_PX else "相關更長",
        },
        "fixed_pattern": {
            "worst_ratio": fixed,
            "verdict": "不顯著" if fixed <= 0.5 else "固定樣式顯著",
        },
        "frame_offset_rel_sigma_worst": max(r["frame_offset_rel_sigma"] for r in rows),
    }


def main(argv: list[str] | None = None) -> int:
    path = Path((argv or sys.argv[1:])[0])
    res = json.loads(path.read_text())
    out = {cam: judge(r["distances"]) for cam, r in res["cameras"].items()}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    doc = {"decision": "028 §4", "range_m": RANGE_M, "cameras": out}
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    (path.parent / "comparison.json").write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
