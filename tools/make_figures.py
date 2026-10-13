"""README figures from the frozen results (reproducible; matplotlib from the detectors extra).

    uv run python tools/make_figures.py

1. docs/figures/accuracy_vs_budget.png - test accuracy vs viewpoint budget, 4 methods
2. docs/figures/three_states.png       - visible / unobservable (+ revealing view) / absent
3. docs/figures/failure_case.png       - a residual Rule-NBV failure from the test report
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from activeperception.framestore import FrameStore  # noqa: E402
from activeperception.serialize import load_episode_set  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures"
# dataviz reference palette (light), fixed slot order; validated: all hard checks pass,
# contrast WARN for aqua / yellow -> every line is direct-labelled and the README has a table
SERIES = {  # slot order = series order
    "rule": ("Rule-based NBV", "#2a78d6"),
    "random": ("Random NBV (5 seeds)", "#eb6834"),
    "single": ("Single view", "#1baf7a"),
    "oracle": ("Oracle NBV (upper bound)", "#eda100"),
}
SURFACE, INK, INK2, MUTED, GRID, BASE = (
    "#fcfcfb",
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
)
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "text.color": INK})


def accuracy_vs_budget(report: dict) -> None:
    budgets = list(range(1, 9))
    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    acc = {k: [report["summary"][f"{k}@{b}"]["accuracy"] for b in budgets] for k in SERIES}
    # Rule and Oracle coincide within 0.004: draw Rule on top so the method stays visible
    z = {"oracle": 2, "single": 3, "random": 4, "rule": 5}
    for key, (label, colour) in SERIES.items():
        ax.plot(
            budgets,
            acc[key],
            color=colour,
            lw=1.5,
            solid_joinstyle="round",
            solid_capstyle="round",
            marker="o",
            ms=5.8,
            mfc=colour,
            mec=SURFACE,
            mew=1.4,
            label=label,
            zorder=z[key],
        )
    # selective direct labels where the lines separate (budget 2), text in ink, not series colour
    ax.annotate(
        f"budget 2: Rule {acc['rule'][1]:.3f}\n              Oracle {acc['oracle'][1]:.3f}",
        xy=(2, acc["rule"][1]),
        xytext=(0.8, 0.9),
        color=INK2,
        fontsize=8,
        va="center",
    )
    ax.annotate(
        f"Random {acc['random'][1]:.3f}",
        xy=(2, acc["random"][1]),
        xytext=(2.25, acc["random"][1] - 0.06),
        color=INK2,
        fontsize=8,
        va="center",
    )
    ax.annotate(
        f"Single view {acc['single'][0]:.3f} at every budget",
        xy=(4, acc["single"][3]),
        xytext=(3.6, acc["single"][3] + 0.06),
        color=INK2,
        fontsize=8,
        va="center",
    )
    ax.annotate(
        f"budget 3: Rule {acc['rule'][2]:.3f}, Random {acc['random'][2]:.3f}",
        xy=(3, acc["random"][2]),
        xytext=(3.25, acc["random"][2] - 0.08),
        color=INK2,
        fontsize=8,
        va="center",
    )
    for b in (1, 2, 3, 5):  # formal budgets (decision 009)
        ax.axvline(b, color=GRID, lw=0.7, zorder=0)
    ax.set_xlim(0.7, 8.3)
    ax.set_ylim(0, 1.06)
    ax.set_xticks(budgets)
    ax.set_xticklabels([f"{b}*" if b in (1, 2, 3, 5) else str(b) for b in budgets])
    ax.set_xlabel("viewpoint budget (views incl. the initial one; * = formal budgets)", color=MUTED)
    ax.set_ylabel("3-class accuracy (test)", color=MUTED)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.tick_params(colors=MUTED, length=0)
    ax.set_title(
        f"Accuracy vs viewpoint budget - core test split ({report['n_episodes']} "
        f"episodes, {report['n_groups']} scene groups)",
        color=INK,
        fontsize=10,
        loc="left",
    )
    ax.legend(loc="center right", frameon=False, fontsize=8, labelcolor=INK2, handlelength=2.4)
    fig.subplots_adjust(right=0.98, left=0.09, bottom=0.14, top=0.9)
    fig.savefig(OUT / "accuracy_vs_budget.png", facecolor=SURFACE)
    plt.close(fig)


def _panel(ax, img, title, sub):
    ax.imshow(img)
    ax.set_title(title, fontsize=9, color=INK, loc="left")
    ax.set_xlabel(sub, fontsize=7.5, color=INK2)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(BASE)


def three_states() -> None:
    specs, gts, _ = load_episode_set(ROOT / "data/episodes/gazebo-pilot.json")
    fs = FrameStore(ROOT / "renders/pilot")
    by_state = {}
    for s in specs:
        by_state.setdefault(str(gts[s.episode_id].state), s)
    vis, unobs, absent = by_state["visible"], by_state["unobservable"], by_state["absent"]
    reveal = max(
        unobs.candidate_viewpoints,
        key=lambda v: gts[unobs.episode_id].visibility_by_viewpoint[v.id],
    )
    fig, axes = plt.subplots(1, 4, figsize=(10, 2.3), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    _panel(axes[0], fs.episode(vis.episode_id).rgb(-1), "visible", "initial view sees the target")
    _panel(
        axes[1], fs.episode(unobs.episode_id).rgb(-1), "unobservable", "initial view: target hidden"
    )
    _panel(
        axes[2],
        fs.episode(unobs.episode_id).rgb(reveal.id),
        "unobservable, another view",
        f"candidate {reveal.id} reveals it -> 'present'",
    )
    _panel(
        axes[3], fs.episode(absent.episode_id).rgb(-1), "absent", "no target; same pillar layout"
    )
    fig.suptitle(
        "Ground-truth states (pilot episodes; Gazebo Harmonic renders)",
        x=0.01,
        ha="left",
        fontsize=10,
        color=INK,
    )
    fig.subplots_adjust(left=0.01, right=0.99, top=0.8, bottom=0.08, wspace=0.04)
    fig.savefig(OUT / "three_states.png", facecolor=SURFACE)
    plt.close(fig)


def failure_case(report: dict) -> None:
    fails = [f for f in report["residual_failures"] if f["budget"] == 3] or report[
        "residual_failures"
    ]
    f = fails[0]
    fs = FrameStore(ROOT / "renders/core")
    fr = fs.episode(f["episode_id"])
    seq = f["viewpoint_sequence"]
    fig, axes = plt.subplots(1, len(seq), figsize=(3.2 * len(seq), 2.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    for ax, vid, zv, mc in zip(
        np.atleast_1d(axes), seq, f["zone_visible"], f["max_conf"], strict=True
    ):
        _panel(ax, fr.rgb(vid), f"view {vid}", f"zone visible {zv:.2f} - max conf {mc:.3f}")
    fig.suptitle(
        f"Residual Rule-NBV failure (test, budget {f['budget']}): {f['episode_id']} "
        f"GT {f['gt_state']} -> {f['decision']}",
        x=0.01,
        ha="left",
        fontsize=9.5,
        color=INK,
    )
    fig.subplots_adjust(left=0.01, right=0.99, top=0.78, bottom=0.1, wspace=0.04)
    fig.savefig(OUT / "failure_case.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rep = json.loads((ROOT / "results/test-v1/report.json").read_text())
    accuracy_vs_budget(rep)
    three_states()
    failure_case(rep)
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
