"""README figures from the frozen results (reproducible; matplotlib from the detectors extra).

    uv run python tools/make_figures.py

1. docs/figures/accuracy_vs_budget.png - test accuracy vs viewpoint budget, 4 methods
2. docs/figures/three_states.png       - visible / unobservable (+ revealing view) / absent
3. docs/figures/failure_case.png       - a residual Rule-NBV failure from the test report
4. docs/figures/holdout_v1_v2.png      - v1 vs v2 accuracy on the holdout (decision 013)
5. docs/figures/failure_attribution.png - Rule failures: structural vs viewpoint choice (dec. 014)
6. docs/figures/nav_teleport_vs_nav2.png - nav-b2: teleport vs Nav2 accuracy (decision 019)
7. docs/figures/nav_b0_lineage.png     - B0 -> nav-b0c -> nav-b0d: arrival, pose error, safety
8. docs/figures/nav_cost.png           - nav-b2: path per episode by state, time per goal

The demo / failure-case animations (docs/figures/demo_nav2_*, failure_nav2_margin.*) come from
tools/make_demo.py on run logs (docs/reproduce.md level B).
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


def holdout_v1_v2(report: dict) -> None:
    """Small multiples, shared y axis: v1 and v2 on the same holdout episodes."""
    budgets = list(range(1, 9))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.6), dpi=200, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    z = {"oracle": 2, "single": 3, "random": 4, "rule": 5}
    for ax, cfg, title in (
        (axes[0], "v1", "v1: decision-v1 + rule-nbv-v1"),
        (axes[1], "v2", "v2: decision-v2 + rule-nbv-v2"),
    ):
        ax.set_facecolor(SURFACE)
        s = report[cfg]["summary"]
        for key, (label, colour) in SERIES.items():
            y = [s[f"{key}@{b}"]["accuracy"] for b in budgets]
            ax.plot(
                budgets,
                y,
                color=colour,
                lw=1.5,
                marker="o",
                ms=5.0,
                mfc=colour,
                mec=SURFACE,
                mew=1.2,
                label=label,
                zorder=z[key],
                solid_joinstyle="round",
            )
        r2, rr2 = s["rule@2"]["accuracy"], s["random@2"]["accuracy"]
        ax.annotate(
            f"budget 2: Rule {r2:.3f}\n              Random {rr2:.3f}",
            xy=(2, r2),
            xytext=(3.2, 0.62),
            color=INK2,
            fontsize=7.5,
            va="center",
        )
        ax.annotate(
            f"Single {s['single@1']['accuracy']:.3f}",
            xy=(6, s["single@6"]["accuracy"]),
            xytext=(5.6, s["single@6"]["accuracy"] + 0.06),
            color=INK2,
            fontsize=7.5,
        )
        for b in (1, 2, 3, 5):
            ax.axvline(b, color=GRID, lw=0.7, zorder=0)
        ax.set_xticks(budgets)
        ax.set_xticklabels([f"{b}*" if b in (1, 2, 3, 5) else str(b) for b in budgets])
        ax.set_ylim(0, 1.06)
        ax.grid(axis="y", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASE)
        ax.tick_params(colors=MUTED, length=0)
        ax.set_title(title, color=INK, fontsize=9, loc="left")
        ax.set_xlabel("viewpoint budget (* = formal)", color=MUTED)
    axes[0].set_ylabel("3-class accuracy (holdout)", color=MUTED)
    axes[1].legend(loc="lower right", frameon=False, fontsize=7.5, labelcolor=INK2)
    fig.suptitle(
        f"Same holdout episodes ({report['n_episodes']} episodes, "
        f"{report['n_groups']} scene groups): v1 vs v2 decision rule and policy",
        x=0.01,
        ha="left",
        fontsize=10,
        color=INK,
    )
    fig.subplots_adjust(left=0.07, right=0.99, bottom=0.15, top=0.82, wspace=0.06)
    fig.savefig(OUT / "holdout_v1_v2.png", facecolor=SURFACE)
    plt.close(fig)


def nav_teleport_vs_nav2(report: dict) -> None:
    """Small multiples, shared y: the same nav-b2 episodes with teleport vs Nav2 + TurtleBot 4."""
    budgets = [1, 2, 3, 4, 5]
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.6), dpi=200, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    z = {"oracle": 2, "single": 3, "random": 4, "rule": 5}
    for ax, key_s, title in (
        (axes[0], "teleport", "teleport (Core harness, exact poses)"),
        (axes[1], "nav2", "Nav2 + TurtleBot 4 (AMCL, relocalised, margin)"),
    ):
        ax.set_facecolor(SURFACE)
        s = report[key_s]
        for key, (label, colour) in SERIES.items():
            label = label.replace("(5 seeds)", "(3 seeds)")
            y = [s[f"{key}@{b}"]["accuracy"] for b in budgets]
            ax.plot(
                budgets,
                y,
                color=colour,
                lw=1.5,
                marker="o",
                ms=5.0,
                mfc=colour,
                mec=SURFACE,
                mew=1.2,
                label=label,
                zorder=z[key],
                solid_joinstyle="round",
            )
        r2, rr2 = s["rule@2"]["accuracy"], s["random@2"]["accuracy"]
        ax.annotate(
            f"budget 2: Rule {r2:.3f}\n              Random {rr2:.3f}",
            xy=(2, r2),
            xytext=(2.6, 0.70),
            color=INK2,
            fontsize=7.5,
            va="center",
        )
        ax.annotate(
            f"Single {s['single@1']['accuracy']:.3f}",
            xy=(4, s["single@4"]["accuracy"]),
            xytext=(3.7, s["single@4"]["accuracy"] + 0.06),
            color=INK2,
            fontsize=7.5,
        )
        for b in (1, 2, 3, 5):
            ax.axvline(b, color=GRID, lw=0.7, zorder=0)
        ax.set_xticks(budgets)
        ax.set_xticklabels([f"{b}*" if b in (2, 3) else str(b) for b in budgets])
        ax.set_ylim(0, 1.06)
        ax.set_title(title, fontsize=9, color=INK, loc="left")
        ax.tick_params(colors=MUTED, labelsize=8, length=0)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(BASE)
        ax.yaxis.grid(True, color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        ax.set_xlabel("viewpoint budget (* = formal)", color=MUTED)
    axes[0].set_ylabel("3-class accuracy (nav-b2)", color=MUTED)
    axes[1].legend(loc="lower right", frameon=False, fontsize=7.5, labelcolor=INK2)
    fig.suptitle(
        f"Same {report['episodes']} nav-b2 episodes: teleport vs real navigation (Nav2)",
        x=0.01,
        ha="left",
        fontsize=10,
        color=INK,
    )
    fig.subplots_adjust(left=0.07, right=0.99, bottom=0.15, top=0.82, wspace=0.06)
    fig.savefig(OUT / "nav_teleport_vs_nav2.png", facecolor=SURFACE)
    plt.close(fig)


def failure_attribution(summary: dict) -> None:
    """Rule failures split by whether the oracle (same decision rule) answers the episode.

    Two categories, not methods, so they take palette slots 7 / 5 (violet, magenta) and
    never the method colours; validated light: all hard checks pass, magenta contrast WARN
    -> every segment is direct-labelled and docs/failure-analysis.md has the table.
    """
    rows = [
        ("test/v1", "v1  (core test, 524)"),
        ("holdout/v1", "v1  (holdout, 600)"),
        ("holdout/ablation", "decision-v2 + rule-nbv-v1  (holdout)"),
        ("holdout/v2", "v2  (holdout, 600)"),
    ]
    cats = (
        ("structural", "Oracle also fails (budget / decision-rule limit)", "#e87ba4"),
        ("policy_gap", "Oracle succeeds (viewpoint choice)", "#4a3aa7"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.3), dpi=200, sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, b in zip(axes, ("2", "3"), strict=True):
        ax.set_facecolor(SURFACE)
        for i, (key, _) in enumerate(rows):
            a = summary["datasets"][key]["rule"][b]["attribution"]
            n, left = a["n_episodes"], 0.0
            y = len(rows) - 1 - i
            for cat, _, colour in cats:
                w = 100.0 * a[cat] / n
                if w > 0:
                    ax.barh(y, w, left=left, height=0.62, color=colour, ec=SURFACE, lw=2)
                left += w
            ax.text(
                left + 0.8,
                y,
                f"{a['structural']} + {a['policy_gap']}",
                va="center",
                fontsize=7.5,
                color=INK2,
            )
        ax.set_title(f"budget {b}", fontsize=9, color=INK, loc="left")
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([label for _, label in reversed(rows)], fontsize=7.5, color=INK2)
        ax.set_xlim(0, 40)
        ax.xaxis.grid(True, color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, labelsize=7.5, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASE)
        ax.set_xlabel("Rule-NBV failures, % of episodes", fontsize=8, color=INK2)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in cats]
    fig.legend(
        handles,
        [label for _, label, _ in cats],
        loc="upper left",
        bbox_to_anchor=(0.005, 0.915),
        ncol=2,
        frameon=False,
        fontsize=7.5,
        labelcolor=INK2,
    )
    fig.suptitle(
        "Where Rule-NBV failures come from (labels: structural + viewpoint choice)",
        x=0.01,
        ha="left",
        y=0.995,
        fontsize=9.5,
        color=INK,
    )
    fig.subplots_adjust(left=0.27, right=0.98, top=0.72, bottom=0.15, wspace=0.08)
    fig.savefig(OUT / "failure_attribution.png", facecolor=SURFACE)
    plt.close(fig)


# two non-method categories (palette slots 7 / 6, violet / green); validated light: all hard
# checks pass (CVD dE 27.9, normal 34.1, contrast >= 3:1); every bar is direct-labelled
POSE_SRC = (
    ("amcl", "AMCL estimate", "#4a3aa7"),
    ("d016", "decision-016 pose (depth-refined)", "#008300"),
)


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.tick_params(colors=MUTED, labelsize=7.5, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.yaxis.grid(True, color=GRID, lw=0.7)
    ax.set_axisbelow(True)


def nav_b0_lineage(fa: dict) -> None:
    """B0 feasibility -> decision 016 -> re-check: one panel per question, same three data sets."""
    rows = {r["namespace"]: r for r in fa["b0_lineage"]}
    names = ["nav-b0", "nav-b0c", "nav-b0d"]
    xt = ["nav-b0\nAMCL only", "nav-b0c\n+ refine, margin", "nav-b0d\n+ relocalise"]
    x = np.arange(3)
    fig, axes = plt.subplots(1, 3, figsize=(9.6, 3.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    _style(ax)
    v = [100 * rows[n]["arrival_rate"] for n in names]
    ax.bar(x, v, width=0.55, color=INK2, ec=SURFACE, lw=2)
    ax.axhline(90, color=MUTED, lw=1.0, ls=(0, (4, 3)))
    ax.text(
        -0.42,
        102.2,
        "dashed: pre-registered threshold 90 %",
        fontsize=6.5,
        color=MUTED,
        va="bottom",
    )
    for i, val in enumerate(v):
        ax.text(
            i,
            val + 0.6,
            f"{val:.1f} %" + ("  below" if val < 90 else ""),
            ha="center",
            fontsize=7.5,
            color=INK,
        )
    ax.set_ylim(70, 104)
    ax.set_title(
        "precise arrival at the viewpoint (GT, scoring only)", fontsize=8.5, color=INK, loc="left"
    )

    ax = axes[1]
    _style(ax)
    w = 0.34
    for k, (key, label, colour) in enumerate(POSE_SRC):
        for i, n in enumerate(names):
            raw = rows[n]["loc_xy_p95_m" if key == "amcl" else "refined_xy_p95_m"]
            xi = i + (k - 0.5) * w
            if raw is None:
                ax.text(xi, 0.12, "not\nused", ha="center", fontsize=6.5, color=MUTED)
                continue
            val = 100 * raw
            ax.bar(
                xi, val, width=w, color=colour, ec=SURFACE, lw=2, label=label if i == 1 else None
            )
            ax.text(xi, val * 1.12, f"{val:.2f}", ha="center", fontsize=7, color=INK)
    ax.set_yscale("log")
    ax.set_ylim(0.1, 60)
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_yticks([0.1, 1, 10])
    ax.set_yticklabels(["0.1", "1", "10"])
    ax.set_ylabel("xy error p95 (cm, log)", fontsize=7.5, color=MUTED)
    ax.set_title("pose used for the decision vs ground truth", fontsize=8.5, color=INK, loc="left")
    ax.legend(loc="upper right", frameon=False, fontsize=6.5, labelcolor=INK2)

    ax = axes[2]
    _style(ax)
    for k, (key, _, colour) in enumerate(POSE_SRC):
        for i, n in enumerate(names):
            val = rows[n][
                "amcl_all_views_risk_episodes" if key == "amcl" else "d016_all_views_risk_episodes"
            ]
            xi = i + (k - 0.5) * w
            if val is None:
                ax.text(xi, 0.08, "not\nused", ha="center", fontsize=6.5, color=MUTED)
                continue
            ax.bar(xi, val, width=w, color=colour, ec=SURFACE, lw=2)
            ax.text(xi, val + 0.08, str(val), ha="center", fontsize=7.5, color=INK)
    ax.set_ylim(0, 6)
    ax.set_yticks(range(0, 7, 2))
    ax.set_title(
        "object present, yet the zone counts as\nfully seen through (unsafe), of 6",
        fontsize=8.5,
        color=INK,
        loc="left",
    )
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(xt, fontsize=7, color=INK2)
    fig.suptitle(
        "Advanced B0: what failed with AMCL poses and what decision 016 changed (simulation)",
        x=0.01,
        ha="left",
        fontsize=9.5,
        color=INK,
    )
    fig.subplots_adjust(left=0.05, right=0.99, bottom=0.2, top=0.76, wspace=0.28)
    fig.savefig(OUT / "nav_b0_lineage.png", facecolor=SURFACE)
    plt.close(fig)


def nav_cost(fa: dict, states: dict[str, str]) -> None:
    """nav-b2 cost: path per episode by GT state (Rule vs Random, method colours) and time per
    goal by relocalisation corrections (one neutral series)."""
    c = fa["cost_per_episode"]
    eps = c["episodes"]
    groups = [
        ("visible", "visible"),
        ("unobservable", "unobservable"),
        ("absent", "absent"),
        ("all", "all 160"),
    ]
    fig, axes = plt.subplots(
        1, 2, figsize=(9.6, 3.3), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]}
    )
    fig.patch.set_facecolor(SURFACE)
    ax = axes[0]
    _style(ax)
    w = 0.36
    for k, m in enumerate(("rule", "random")):
        label, colour = SERIES[m]
        label = label.replace("(5 seeds)", "(3 seeds)")
        for i, (g, _) in enumerate(groups):
            idx = [j for j, e in enumerate(eps) if g == "all" or states[e] == g]
            val = float(np.mean([c[f"{m}_path_m"][j] for j in idx]))
            xi = i + (k - 0.5) * w
            ax.bar(
                xi, val, width=w, color=colour, ec=SURFACE, lw=2, label=label if i == 0 else None
            )
            ax.text(xi, val + 0.06, f"{val:.2f}", ha="center", fontsize=7, color=INK)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(
        [f"{t}\n(n={sum(1 for e in eps if g == 'all' or states[e] == g)})" for g, t in groups],
        fontsize=7,
        color=INK2,
    )
    ax.set_ylabel("metres driven per episode", fontsize=7.5, color=MUTED)
    ax.set_title(
        "distance driven (Nav2, budget 5 run; visible = answered at the start)",
        fontsize=8.5,
        color=INK,
        loc="left",
    )
    ax.legend(loc="upper left", frameon=False, fontsize=7, labelcolor=INK2)
    ax.set_ylim(0, 5)

    ax = axes[1]
    _style(ax)
    r = fa["relocalization"]
    ks = [str(k) for k in range(r["max_corrections"] + 1)]
    vals = [r["sim_s_p50_by_corrections"][k] for k in ks]
    ax.bar(range(len(ks)), vals, width=0.55, color=INK2, ec=SURFACE, lw=2)
    for i, val in enumerate(vals):
        ax.text(i, val + 0.4, f"{val:.1f} s", ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(range(len(ks)))
    ax.set_xticklabels(
        [f"{k} correction{'' if k == '1' else 's'}\n(n={r['corrections_used'][k]})" for k in ks],
        fontsize=7,
        color=INK2,
    )
    ax.set_ylabel("simulated seconds per goal (p50)", fontsize=7.5, color=MUTED)
    ax.set_title("time per goal vs stop relocalisation", fontsize=8.5, color=INK, loc="left")
    ax.set_ylim(0, 27)
    fig.suptitle(
        f"Cost of real navigation on nav-b2 ({r['navigations']} navigations, simulation)",
        x=0.01,
        ha="left",
        fontsize=9.5,
        color=INK,
    )
    fig.subplots_adjust(left=0.06, right=0.99, bottom=0.2, top=0.8, wspace=0.22)
    fig.savefig(OUT / "nav_cost.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    rep = json.loads((ROOT / "results/test-v1/report.json").read_text())
    accuracy_vs_budget(rep)
    # these two read camera frames: renders/ is not in git (rebuild: docs/reproduce.md level C)
    if (ROOT / "renders/pilot").exists():
        three_states()
    else:
        print("skip three_states.png (no renders/pilot)")
    if (ROOT / "renders/core").exists():
        failure_case(rep)
    else:
        print("skip failure_case.png (no renders/core)")
    holdout = ROOT / "results/holdout/report.json"
    if holdout.exists():
        holdout_v1_v2(json.loads(holdout.read_text()))
    fa = ROOT / "results/failure-analysis/summary.json"
    if fa.exists():
        failure_attribution(json.loads(fa.read_text()))
    b2 = ROOT / "results/nav-b2/b1_report.json"
    if b2.exists():
        nav_teleport_vs_nav2(json.loads(b2.read_text()))
    nfa = ROOT / "results/nav-failure-analysis/summary.json"
    if nfa.exists():
        fa_nav = json.loads(nfa.read_text())
        nav_b0_lineage(fa_nav)
        _, gts, _ = load_episode_set(ROOT / "data/episodes/gazebo-nav-b2.json")
        nav_cost(fa_nav, {e: g.state.value for e, g in gts.items()})
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
