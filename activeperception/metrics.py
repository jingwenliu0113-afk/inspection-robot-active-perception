"""Aggregate metrics with cluster bootstrap confidence intervals.

Cluster = scene group (all variants of a scene are resampled together).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

import numpy as np

from .grader import Outcome
from .types import Decision, GroundTruthState

CLASSES = (Decision.PRESENT, Decision.ABSENT, Decision.INCONCLUSIVE)


def _rate(flags: Sequence[bool]) -> float | None:
    return float(np.mean(flags)) if len(flags) else None


def accuracy(outcomes: Sequence[Outcome]) -> float | None:
    return _rate([o.correct for o in outcomes])


def macro_f1(outcomes: Sequence[Outcome]) -> float | None:
    """Macro-F1 over the classes that occur in expected or predicted labels."""
    if not outcomes:
        return None
    exp = [o.expected for o in outcomes]
    pred = [o.decision for o in outcomes]
    present = [c for c in CLASSES if c in exp or c in pred]
    f1s = []
    for c in present:
        tp = sum(1 for e, p in zip(exp, pred, strict=True) if e == c and p == c)
        fp = sum(1 for e, p in zip(exp, pred, strict=True) if e != c and p == c)
        fn = sum(1 for e, p in zip(exp, pred, strict=True) if e == c and p != c)
        denom = 2 * tp + fp + fn
        f1s.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(f1s))


def false_absent_rate(outcomes: Sequence[Outcome]) -> float | None:
    """Among episodes where the object exists: fraction answered ``absent``."""
    return _rate([o.false_absent for o in outcomes if o.gt_state != GroundTruthState.ABSENT])


def false_present_rate(outcomes: Sequence[Outcome]) -> float | None:
    return _rate([o.false_present for o in outcomes if o.gt_state == GroundTruthState.ABSENT])


def inconclusive_rate(outcomes: Sequence[Outcome]) -> float | None:
    return _rate([o.inconclusive for o in outcomes])


def avg_viewpoints(outcomes: Sequence[Outcome]) -> float | None:
    return float(np.mean([o.viewpoints_used for o in outcomes])) if outcomes else None


def expected_calibration_error(outcomes: Sequence[Outcome], n_bins: int = 10) -> float | None:
    """ECE over *definitive* decisions (present / absent) using the stated confidence."""
    definitive = [o for o in outcomes if o.decision != Decision.INCONCLUSIVE]
    if not definitive:
        return None
    conf = np.array([o.confidence for o in definitive])
    corr = np.array([o.correct for o in definitive], dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1], right=False), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(corr[m].mean() - conf[m].mean())
    return float(ece)


def reliability_bins(outcomes: Sequence[Outcome], n_bins: int = 10) -> list[dict]:
    definitive = [o for o in outcomes if o.decision != Decision.INCONCLUSIVE]
    conf = np.array([o.confidence for o in definitive])
    corr = np.array([o.correct for o in definitive], dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    if len(definitive):
        idx = np.clip(np.digitize(conf, edges[1:-1], right=False), 0, n_bins - 1)
        for b in range(n_bins):
            m = idx == b
            rows.append(
                {
                    "bin_lo": float(edges[b]),
                    "bin_hi": float(edges[b + 1]),
                    "n": int(m.sum()),
                    "mean_confidence": float(conf[m].mean()) if m.any() else None,
                    "accuracy": float(corr[m].mean()) if m.any() else None,
                }
            )
    return rows


STATS: dict[str, Callable[[Sequence[Outcome]], float | None]] = {
    "accuracy": accuracy,
    "macro_f1": macro_f1,
    "false_absent_rate": false_absent_rate,
    "false_present_rate": false_present_rate,
    "inconclusive_rate": inconclusive_rate,
    "avg_viewpoints": avg_viewpoints,
    "ece": expected_calibration_error,
}


def cluster_bootstrap(
    outcomes: Sequence[Outcome],
    stat: Callable[[Sequence[Outcome]], float | None],
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float] | None:
    """Percentile CI by resampling scene groups with replacement."""
    by_group: dict[int, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_group[o.scene_group].append(o)
    groups = sorted(by_group)
    if len(groups) < 2:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), size=len(groups))
        sample = [o for g in pick for o in by_group[groups[g]]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def summarize(outcomes: Sequence[Outcome], n_boot: int = 0, seed: int = 0) -> dict:
    out: dict = {"n": len(outcomes), "n_groups": len({o.scene_group for o in outcomes})}
    for name, fn in STATS.items():
        out[name] = fn(outcomes)
        if n_boot:
            out[f"{name}_ci95"] = cluster_bootstrap(outcomes, fn, n_boot=n_boot, seed=seed)
    out["by_state"] = {}
    for state in GroundTruthState:
        sub = [o for o in outcomes if o.gt_state == state]
        out["by_state"][str(state)] = {
            "n": len(sub),
            "accuracy": accuracy(sub),
            "false_absent_rate": false_absent_rate(sub)
            if state != GroundTruthState.ABSENT
            else None,
            "false_present_rate": false_present_rate(sub)
            if state == GroundTruthState.ABSENT
            else None,
            "inconclusive_rate": inconclusive_rate(sub),
            "avg_viewpoints": avg_viewpoints(sub),
        }
    out["reliability"] = reliability_bins(outcomes)
    return out


def _fmt(v, ci=None) -> str:
    if v is None:
        return "-"
    s = f"{v:.3f}"
    if ci:
        s += f" [{ci[0]:.2f}, {ci[1]:.2f}]"
    return s


def markdown_table(summaries: dict[tuple[str, int], dict]) -> str:
    cols = [
        "accuracy",
        "macro_f1",
        "false_absent_rate",
        "false_present_rate",
        "inconclusive_rate",
        "avg_viewpoints",
        "ece",
    ]
    lines = [
        "| policy | budget | n | " + " | ".join(cols) + " |",
        "|---|---|---|" + "|".join("---" for _ in cols) + "|",
    ]
    for (policy, budget), s in sorted(summaries.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        cells = [_fmt(s.get(c), s.get(f"{c}_ci95")) for c in cols]
        lines.append(f"| {policy} | {budget} | {s['n']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
