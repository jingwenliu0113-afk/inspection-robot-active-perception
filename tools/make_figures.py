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
9. docs/figures/r0a_real_images.png    - R0a: frozen detector on real photos (decision 021)
10. docs/figures/r0b_noise.png        - R0b: v2 safety under modelled depth / pose error
11. docs/figures/v3_dev_ablation.png  - v3 development: geometry ablation, zone gating (dec. 024)
12. docs/figures/v3_formal.png        - v3 formal test once: v2 vs v3 on new data (decision 026)

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


def r0a_real_images(report: dict, rows: list[dict], dets: dict) -> None:
    """R0a (decision 021): recall by stratum, synthetic pillar occlusion, c_max distributions.

    Two non-method categories per panel: slots 7 / 6 (violet / green), validated as a pair
    (all hard checks pass); every series is direct-labelled or in a legend.
    """
    from activeperception import r0a

    cam = report["summary"]["camera"]
    fig, axes = plt.subplots(
        1, 3, figsize=(10.4, 3.5), dpi=200, gridspec_kw={"width_ratios": [1.1, 1, 1.2]}
    )
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    _style(ax)
    strata = [st for st in r0a.MAIN_STRATA if st in cam["positives"]]
    for i, st in enumerate(strata):
        r = cam["positives"][st]["localized_recall_at_present"]
        lo, hi = r["ci95"]
        ax.bar(i, 100 * r["rate"], width=0.6, color=INK2, ec=SURFACE, lw=2)
        ax.plot([i, i], [100 * lo, 100 * hi], color=MUTED, lw=1.2)
        ax.text(i, 100 * hi + 2, f"{r['k']}/{r['n']}", ha="center", fontsize=7, color=INK)
    ax.axhline(90, color=MUTED, lw=1.0, ls=(0, (4, 3)))
    ax.set_xticks(range(len(strata)))
    ax.set_xticklabels(strata, fontsize=7.5, color=INK2)
    ax.set_ylim(0, 112)
    ax.set_ylabel("% detected at >= 0.7 on the hydrant", fontsize=7.5, color=MUTED)
    ax.set_title(
        "real photos, by annotation (A1: clear >= 90%)", fontsize=8.5, color=INK, loc="left"
    )

    ax = axes[1]
    _style(ax)
    fr = [0, *[int(100 * f) for f in r0a.OCCLUSION_FRACTIONS]]
    series = (
        ("present_rate", "detected >= 0.7", "#4a3aa7"),
        ("complete_miss", "max conf < 0.02", "#008300"),
    )
    for key, label, colour in series:
        rs = [cam["positives"]["clear"][key]] + [
            report["summary"][f"occ{f}"]["positives"]["clear"][key] for f in fr[1:]
        ]
        y = [100 * r["rate"] for r in rs]
        ax.fill_between(
            fr,
            [100 * r["ci95"][0] for r in rs],
            [100 * r["ci95"][1] for r in rs],
            color=colour,
            alpha=0.12,
            lw=0,
        )
        ax.plot(fr, y, color=colour, lw=2, marker="o", ms=5, mec=SURFACE, mew=1.2)
        ax.text(fr[-1] + 2, y[-1], label, fontsize=7, color=INK2, va="center")
    ax.set_xticks(fr)
    ax.set_xticklabels([f"{f}%" for f in fr], fontsize=7.5, color=INK2)
    ax.set_xlim(-5, 115)
    ax.set_ylim(0, 105)
    ax.set_xlabel("hydrant box width covered by a grey 'pillar'", fontsize=7.5, color=MUTED)
    ax.set_title("clear photos + synthetic occlusion", fontsize=8.5, color=INK, loc="left")

    ax = axes[2]
    _style(ax)
    bins = np.logspace(-3, 0, 31)
    groups = (
        ("neg", None, "no hydrant (verified, hard)", "#4a3aa7"),
        ("pos", "clear", "clear hydrant", "#008300"),
    )
    for label, st, name, colour in groups:
        c = [
            max((d[0] for d in dets[r["image_id"]]["detections"]), default=1e-3)
            for r in rows
            if r["label"] == label and (st is None or r["stratum"] == st) and r["image_id"] in dets
        ]
        ax.hist(
            np.clip(c, 1e-3, 1), bins=bins, color=colour, alpha=0.55, label=f"{name} (n={len(c)})"
        )
    ax.set_xscale("log")
    ymax = ax.get_ylim()[1]
    for t, lab in ((r0a.TAU_ABSENT, "absent needs < 0.02"), (r0a.TAU_PRESENT, "present >= 0.7")):
        ax.axvline(t, color=MUTED, lw=1.0, ls=(0, (4, 3)))
        ax.text(
            t / 1.08, ymax * 0.68, lab, fontsize=6.5, color=MUTED, rotation=90, ha="right", va="top"
        )
    ax.set_xlabel("highest hydrant confidence (<= 0.001 incl. none)", fontsize=7.5, color=MUTED)
    ax.set_ylabel("images", fontsize=7.5, color=MUTED)
    ax.legend(loc="upper left", frameon=False, fontsize=6.5, labelcolor=INK2)
    ax.set_title("confidence distribution", fontsize=8.5, color=INK, loc="left")
    fig.suptitle(
        "R0a: frozen detector-v1 on real photos (Open Images, ~640x480 px) - not a robot camera",
        x=0.01,
        ha="left",
        fontsize=9.5,
        color=INK,
    )
    fig.subplots_adjust(left=0.06, right=0.99, bottom=0.17, top=0.82, wspace=0.3)
    fig.savefig(OUT / "r0a_real_images.png", facecolor=SURFACE)
    plt.close(fig)


def r0b_noise(report: dict) -> None:
    """R0b (decision 023): occupied-location false clearance per condition (sequential blue
    ramp, one hue; every cell is labelled with its count and safe / UNSAFE in ink), and the
    cost for pipeline (b) as Rule accuracy."""
    from matplotlib.colors import LinearSegmentedColormap

    from activeperception import r0b

    ramp = LinearSegmentedColormap.from_list(
        "blue", ["#f4f8fd", "#b7d3f6", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"]
    )
    by = {tuple(r["condition"].values()): r for r in report["results"]}
    depths, poses = list(r0b.DEPTH_LEVELS), list(r0b.POSE_LEVELS)
    rate = {
        k: v["occupied_false_clearance"]["views"] / v["occupied_false_clearance"]["present_views"]
        for k, v in by.items()
    }
    vmax = max(max(rate.values()), 0.05)
    fig, axes = plt.subplots(
        1, 3, figsize=(10.4, 3.6), dpi=200, gridspec_kw={"width_ratios": [1, 1, 1.25]}
    )
    fig.patch.set_facecolor(SURFACE)
    titles = {"a": "(a) estimated pose used directly", "b": "(b) + decision 016 (refine, margin)"}
    for ax, pipe in zip(axes[:2], r0b.PIPELINES, strict=True):
        grid = np.array([[rate[(d, q, pipe)] for q in poses] for d in depths])
        ax.imshow(grid, cmap=ramp, vmin=0, vmax=vmax)
        for i, d in enumerate(depths):
            for j, q in enumerate(poses):
                r = by[(d, q, pipe)]
                occ = r["occupied_false_clearance"]
                n_ep = len(r["all_views_geometric_risk"])
                verdict = "safe" if r0b.safe(r) else f"UNSAFE\n{n_ep} all-view ep"
                dark = grid[i, j] > 0.55 * vmax
                ax.text(
                    j,
                    i,
                    f"{occ['views']}/{occ['present_views']}\n{verdict}",
                    ha="center",
                    va="center",
                    fontsize=6.3,
                    color=SURFACE if dark else INK,
                )
        ax.set_xticks(range(len(poses)))
        ax.set_xticklabels(poses, fontsize=7.5, color=INK2)
        ax.set_yticks(range(len(depths)))
        ax.set_yticklabels(depths, fontsize=7.5, color=INK2)
        ax.set_xlabel("pose error level", fontsize=7.5, color=MUTED)
        ax.set_title(titles[pipe], fontsize=8.5, color=INK, loc="left")
        for side in ax.spines.values():
            side.set_visible(False)
        ax.tick_params(length=0)
    axes[0].set_ylabel("depth noise level", fontsize=7.5, color=MUTED)

    ax = axes[2]
    _style(ax)
    labels = [f"{d}x{q}" for d in depths for q in poses]
    x = np.arange(len(labels))
    for b, colour, off in ((2, "#4a3aa7", -0.2), (3, "#008300", 0.2)):
        y = [by[(d, q, "b")]["summary"][f"rule@{b}"]["accuracy"] for d in depths for q in poses]
        ax.bar(
            x + off,
            y,
            width=0.38,
            color=colour,
            ec=SURFACE,
            lw=1.5,
            label=f"Rule-NBV v2, budget {b}",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.5, color=INK2, rotation=45, ha="right")
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("3-class accuracy, pipeline (b)", fontsize=7.5, color=MUTED)
    ax.legend(loc="upper right", frameon=False, fontsize=6.5, labelcolor=INK2)
    ax.set_title(
        "cost: absent needs all 64 places seen through", fontsize=8.5, color=INK, loc="left"
    )
    fig.suptitle(
        "R0b: views where a place under the hydrant counts as seen through "
        "(cell: views / present views) - simulated sensor error",
        x=0.01,
        ha="left",
        fontsize=9,
        color=INK,
    )
    fig.subplots_adjust(left=0.05, right=0.99, bottom=0.22, top=0.84, wspace=0.28)
    fig.savefig(OUT / "r0b_noise.png", facecolor=SURFACE)
    plt.close(fig)


def v3_dev_ablation(rows: list[dict]) -> None:
    """v3 development data (decision 024): unsafe views per geometry config (count, labelled),
    absent reachability, and zone gating on the distractor scenes. Two conditions = two fixed
    categorical slots; every bar carries its value in ink."""
    by = {(r["ns"], r["condition"], r["config"], r["gated"]): r for r in rows}
    configs = [
        ("v2", "v2\n(dec. 016)"),
        ("see", "+ see-\nthrough-v3"),
        ("pose", "+ nav-\npose-v3"),
        ("m4", "+ margin\n4 cm"),
        ("m4p", "+ prior\ngate"),
        ("m6p", "margin\n6 cm"),
        ("m6c", "+ conflict\n= frozen v3"),
    ]
    conds = (("D1xL1", "D1 x L1 (typical)", "#4a3aa7"), ("D2xL2", "D2 x L2 (stress)", "#008300"))
    fig, axes = plt.subplots(
        1, 3, figsize=(12.6, 3.9), dpi=200, gridspec_kw={"width_ratios": [1.45, 1.45, 0.8]}
    )
    fig.patch.set_facecolor(SURFACE)
    x = np.arange(len(configs))
    panels = (
        ("occupied", "(a) views where a place under the hydrant\n     counts as seen through"),
        ("absent_b5", "(b) Rule, budget 5: absent episodes\n     answered 'absent'"),
    )
    for ax, (field, title) in zip(axes[:2], panels, strict=True):
        _style(ax)
        for (c, label, colour), off in zip(conds, (-0.2, 0.2), strict=True):
            rows_c = [
                by.get(("v3-dev", c, k, False)) or by[("v3-dev", c, k, True)] for k, _ in configs
            ]
            vals = [r[field] for r in rows_c]
            ax.bar(x + off, vals, width=0.38, color=colour, ec=SURFACE, lw=1.5, label=label)
            for xi, v in zip(x + off, vals, strict=True):
                txt = f"{v}" if field == "occupied" else f"{v:.2f}"
                ax.text(xi, v, txt, ha="center", va="bottom", fontsize=5.2, color=INK2)
        ax.set_xticks(x)
        ax.set_xticklabels([n for _, n in configs], fontsize=5.9, color=INK2)
        ax.set_title(title, fontsize=8, color=INK, loc="left")
    axes[0].set_ylabel("views (of 780 with the object present)", fontsize=7, color=MUTED)
    axes[0].set_ylim(0, 6)
    axes[1].set_ylim(0, 1.12)
    axes[0].legend(loc="upper right", frameon=False, fontsize=6.5, labelcolor=INK2)

    ax = axes[2]
    _style(ax)
    gx = np.arange(2)
    for gated, colour, off, label in (
        (False, "#c3c2b7", -0.2, "v2: best detection anywhere"),
        (True, "#2a78d6", 0.2, "decision-v3: in-zone only"),
    ):
        vals = [by[("v3-dev-dx", c, "v2", gated)]["false_present"] for c in ("D0xP0", "D1xL1")]
        ax.bar(gx + off, vals, width=0.38, color=colour, ec=SURFACE, lw=1.5, label=label)
        for xi, v in zip(gx + off, vals, strict=True):
            ax.text(xi, v, f"{v}", ha="center", va="bottom", fontsize=6.3, color=INK2)
    ax.set_xticks(gx)
    ax.set_xticklabels(["D0 x P0", "D1 x L1"], fontsize=7, color=INK2)
    ax.set_ylim(0, 980)
    ax.set_ylabel("false present (4 methods x budgets 1-5)", fontsize=7, color=MUTED)
    ax.legend(loc="upper left", frameon=False, fontsize=6.3, labelcolor=INK2)
    title = "(c) hydrant outside the zone\n     (v3-dev-dx)"
    ax.set_title(title, fontsize=8, color=INK, loc="left")
    fig.suptitle(
        "v3 development data (not a formal result): what each component fixes "
        "- simulated depth / pose error",
        x=0.01,
        ha="left",
        fontsize=9,
        color=INK,
    )
    fig.subplots_adjust(left=0.06, right=0.99, bottom=0.17, top=0.8, wspace=0.3)
    fig.savefig(OUT / "v3_dev_ablation.png", facecolor=SURFACE)
    plt.close(fig)


def v3_formal(report: dict) -> None:
    """decision 026: v2 vs v3 on the formal sets (two fixed slots; every bar labelled in ink)."""
    conds = [
        ("v3:D0xP0", "D0 x P0\nclean"),
        ("v3:D1xL1", "D1 x L1\ntypical (V1/V2)"),
        ("v3:D2xL2", "D2 x L2\nstress (V4)"),
        ("v3:D1xL2-reportsL1", "D1 x L2,\nlocaliser 2x\nover-confident (V5)"),
        ("v3-dx:D0xP0", "hydrant outside\nzone, D0 x P0 (V3)"),
        ("v3-dx:D1xL1", "hydrant outside\nzone, D1 x L1 (V3)"),
    ]
    res = report["results"]
    pipes = (
        ("v2", "v2 (decision 016, no zone gating)", "#a8a69e"),
        ("v3", "v3 (frozen, decision 025)", "#2a78d6"),
    )
    panels = (
        ("absent", "(a) Rule, budget 5: absent episodes answered 'absent' (of 80)"),
        ("fp", "(b) false present (4 methods x budgets 1-5)"),
        ("occ", "(c) views with a place under the hydrant 'seen through' (of 1040)"),
    )
    fig, axes = plt.subplots(3, 1, figsize=(10.4, 7.6), dpi=200, sharex=True)
    fig.patch.set_facecolor(SURFACE)
    x = np.arange(len(conds))

    def value(c, field):
        if field == "absent":
            return round(c["summary"]["rule@5"]["accuracy_by_state"]["absent"] * 80)
        if field == "fp":
            return c["false_present"]
        return c["occupied_false_clearance"]["views"]

    for ax, (field, title) in zip(axes, panels, strict=True):
        _style(ax)
        for (pipe, label, colour), off in zip(pipes, (-0.2, 0.2), strict=True):
            vals = [value(res[f"{k}:{pipe}"], field) for k, _ in conds]
            ax.bar(x + off, vals, width=0.38, color=colour, ec=SURFACE, lw=1.5, label=label)
            for xi, v in zip(x + off, vals, strict=True):
                ax.text(xi, v, f"{v}", ha="center", va="bottom", fontsize=6.3, color=INK2)
        ax.set_title(title, fontsize=8.5, color=INK, loc="left")
    axes[0].set_ylim(0, 95)
    axes[1].legend(loc="upper left", frameon=False, fontsize=7, labelcolor=INK2)
    axes[1].set_ylim(0, 1450)
    axes[2].set_ylim(0, 3)
    axes[2].set_yticks([0, 1, 2, 3])
    note = "V4 fails: one view, refined pose 34.9 cm off\n(FA / GR stay 0)"
    axes[2].text(2.2, 1.15, note, fontsize=6.5, color=INK2, va="bottom")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels([n for _, n in conds], fontsize=6.8, color=INK2)
    fig.suptitle(
        "v3 formal test, run once on new data (decision 026) - simulated depth / pose error, "
        "not a real robot",
        x=0.01,
        ha="left",
        fontsize=9,
        color=INK,
    )
    fig.subplots_adjust(left=0.05, right=0.99, bottom=0.11, top=0.92, hspace=0.42)
    fig.savefig(OUT / "v3_formal.png", facecolor=SURFACE)
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
    r0a_rep = ROOT / "results/r0a/report.json"
    if r0a_rep.exists():
        from activeperception import r0a

        r0a_real_images(
            json.loads(r0a_rep.read_text()),
            r0a.read_csv(ROOT / "data/r0a/manifest-formal.csv"),
            r0a.load_detections(ROOT / "results/r0a/detections-formal.jsonl")["camera"],
        )
    r0b_rep = ROOT / "results/r0b/report.json"
    if r0b_rep.exists():
        r0b_noise(json.loads(r0b_rep.read_text()))
    v3_rep = ROOT / "results/v3/report.json"
    if v3_rep.exists():
        v3_formal(json.loads(v3_rep.read_text()))
    v3_dev = ROOT / "results/v3-dev/ablation.json"
    if v3_dev.exists():
        v3_dev_ablation(json.loads(v3_dev.read_text())["rows"])
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
