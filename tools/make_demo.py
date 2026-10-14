"""Demo of one Nav2 closed-loop episode: animated GIF and / or a static storyboard.

    uv run python tools/make_demo.py --ns nav-b1 --run runs/nav-b1/nav-b1-g0001-v2/rule-s0 \
        --gif docs/figures/demo_nav2_unobservable.gif
    uv run python tools/make_demo.py --ns nav-b1 --run runs/nav-b1/nav-b1-g0001-v3/rule-s0 \
        --png docs/figures/demo_nav2_absent.png

Input is one ``b1_driver`` run directory (``run.json``, ``cap_XX.npz``, ``trace_XX.npy``),
e.g. from ``docker/demo.sh``. Left: top-down view (facility walls and pillars, inspection
zone, the 12 candidate viewpoints, the 64 places the object could stand - green once seen
through - and the robot). Right: the onboard camera frame, detector boxes and the decision
after each view.

The decision inputs are rebuilt from deployable data only, exactly as the driver built them
(AMCL estimate -> depth refinement -> decision-016 see-through; onboard detections), and the
rebuilt seen-through fraction is checked against ``run.json``. The drawn path, robot pose and
target marker come from simulator ground truth and are for the viewer only.
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402
from PIL import Image  # noqa: E402

from activeperception import frozen_v2  # noqa: E402
from activeperception.detector.cache import make_detection  # noqa: E402
from activeperception.framestore import decode_depth_mm  # noqa: E402
from activeperception.nav import scene  # noqa: E402
from activeperception.nav.observe import deployable_camera_pose, observation_d016  # noqa: E402
from activeperception.sensing import cleared_locations, location_grid  # noqa: E402
from activeperception.serialize import load_episode_set  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
PATH = "#2a78d6"  # Rule-NBV's series colour in every other figure
CLEARED = "#008300"
BOX = "#eda100"
WALL, PILLAR = "#52514e", "#c3c2b7"
HYDRANT = "#e34948"
DV2 = frozen_v2.DECISION_V2  # thresholds quoted in the frames come from the frozen config
POLICY_NAMES = {
    "rule": "Rule-NBV v2",
    "random": "Random NBV",
    "single": "Single view",
    "oracle": "Oracle (GT)",
}
VIEW_HALF_M = 2.6  # the 2.0 m viewpoint ring plus the robot
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "text.color": INK})


def load_run(ns: str, run_dir: Path):
    specs, gts, _ = load_episode_set(f"data/episodes/gazebo-{ns}.json")
    run = json.loads((run_dir / "run.json").read_text())
    spec = {s.episode_id: s for s in specs}[run["episode_id"]]
    return spec, gts[spec.episode_id], run


def rebuild(spec, run: dict, run_dir: Path) -> list[dict]:
    """Per view: frame, deployable decision input, policy scores for the next pick."""
    rule = frozen_v2.decision_rule()
    policy = frozen_v2.rule_nbv() if run["policy"] == "rule" else None
    ep = spec.deployable()
    if policy:
        policy.reset(ep, run["seed"])
    hist, views = [], []
    for k, st in enumerate(run["steps"]):
        cap = np.load(run_dir / st["file"])
        depth = decode_depth_mm(cap["depth_mm"])
        h, w = depth.shape
        dets = tuple(make_detection(d[0], d[1:5], w, h) for d in st["observation"]["detections"])
        pose = deployable_camera_pose(st["deployable"]["estimate"])
        obs, _ = observation_d016(spec, st["target"], depth, dets, pose)
        hist.append(obs)
        cleared = cleared_locations(hist, rule.params.col_min)
        if abs(cleared.mean() - st["cleared_fraction"]) > 1e-9:
            raise SystemExit(f"view {k}: rebuilt see-through {cleared.mean()} != run.json")
        scores = None
        if policy and k + 1 < len(run["steps"]):
            uncleared = ~cleared
            p = policy.params
            scores = []
            for vp in (
                c for c in ep.candidate_viewpoints if c.id not in {o.viewpoint_id for o in hist}
            ):
                f = policy.features(ep, hist, vp, uncleared)
                s = (
                    p.w_gain * f["clear_gain"]
                    + p.w_novelty * f["novelty"]
                    + p.w_attraction * f["attraction"]
                    + p.w_visibility * f.get("predicted_visibility", 0.0)
                )
                scores.append((s, vp.id))
            scores.sort(key=lambda t: (-t[0], t[1]))  # = RuleNBVv2Policy.select_next
            if scores[0][1] != run["steps"][k + 1]["target"]:
                raise SystemExit(f"view {k}: rebuilt policy pick {scores[0]} != run.json")
        nav = st.get("nav")
        trace = np.load(run_dir / nav["trace_file"]) if nav else None
        views.append(
            {
                "rgb": cap["rgb"],
                "target": st["target"],
                "decision": st["decision"],
                "max_conf": max(o.max_confidence for o in hist),
                "dets": st["observation"]["detections"],
                "cleared": cleared.copy(),
                "gt_base": st["scoring"]["gt_base"],
                "trace": trace,
                "reloc": (nav or {}).get("relocalize"),
                "nav_sim_s": (nav or {}).get("sim_s"),
                "scores": scores,
            }
        )
    return views


def draw_map(ax, spec, gt, views, upto: int, robot=None, path_xy=None) -> None:
    ax.set_facecolor(SURFACE)
    for b in scene.walls():
        ax.add_patch(Rectangle((b.cx - b.sx / 2, b.cy - b.sy / 2), b.sx, b.sy, color=WALL, lw=0))
    for b in spec.layout.occluders:
        ax.add_patch(Rectangle((b.cx - b.sx / 2, b.cy - b.sy / 2), b.sx, b.sy, color=PILLAR, lw=0))
    z = spec.zone
    ax.add_patch(Circle((z.cx, z.cy), z.radius, fill=False, ec=INK2, lw=0.8, ls=(0, (3, 2))))
    grid = location_grid(z)
    cl = views[upto]["cleared"] if upto >= 0 else np.zeros(len(grid), bool)
    ax.scatter(
        grid[~cl, 0], grid[~cl, 1], s=5, facecolors="none", edgecolors=MUTED, lw=0.5, zorder=3
    )
    ax.scatter(grid[cl, 0], grid[cl, 1], s=6, color=CLEARED, lw=0, zorder=3)
    visited = {v["target"] for v in views[: upto + 1]}
    for vp in spec.candidate_viewpoints:
        hit = vp.id in visited
        ax.add_patch(
            Circle(
                (vp.pose.x, vp.pose.y),
                0.13,
                fill=hit,
                color=PATH if hit else MUTED,
                alpha=0.9 if hit else 0.6,
                lw=0.8,
            )
        )
        ax.text(
            vp.pose.x,
            vp.pose.y,
            str(vp.id),
            ha="center",
            va="center",
            fontsize=5.5,
            color=SURFACE if hit else INK2,
        )
    s0 = spec.initial_viewpoint.pose
    ax.text(s0.x, s0.y - 0.32, "start", ha="center", va="top", fontsize=6.5, color=INK2)
    if spec.layout.object_present:
        o = spec.layout.object_pose
        ax.add_patch(Circle((o.x, o.y), spec.layout.object_radius, color=HYDRANT, alpha=0.85, lw=0))
    if path_xy is not None and len(path_xy) > 1:
        ax.plot(path_xy[:, 0], path_xy[:, 1], color=PATH, lw=1.6, solid_capstyle="round", zorder=4)
    if robot is not None:
        x, y, yaw = robot
        fov, rng = math.radians(30), 2.7
        wedge = [
            (x, y),
            (x + rng * math.cos(yaw - fov), y + rng * math.sin(yaw - fov)),
            (x + rng * math.cos(yaw + fov), y + rng * math.sin(yaw + fov)),
        ]
        ax.add_patch(Polygon(wedge, closed=True, color=PATH, alpha=0.10, lw=0, zorder=2))
        ax.add_patch(Circle((x, y), 0.17, color=INK, zorder=5))
        ax.plot(
            [x, x + 0.3 * math.cos(yaw)],
            [y, y + 0.3 * math.sin(yaw)],
            color=SURFACE,
            lw=1.5,
            zorder=6,
        )
    ax.set_xlim(-VIEW_HALF_M, VIEW_HALF_M)
    ax.set_ylim(-VIEW_HALF_M, VIEW_HALF_M)
    ax.text(
        VIEW_HALF_M - 0.05,
        VIEW_HALF_M - 0.05,
        "enclosure walls at +-4 m\n(off view)",
        fontsize=5.5,
        color=MUTED,
        ha="right",
        va="top",
    )
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_visible(False)


def legend(fig, top: bool = False) -> None:
    items = [
        (Circle((0, 0), 1, color=PILLAR), "pillar (facility map)"),
        (Circle((0, 0), 1, fill=False, ec=MUTED), "place the object could stand"),
        (Circle((0, 0), 1, color=CLEARED), "... seen through (empty)"),
        (Circle((0, 0), 1, color=HYDRANT), "hydrant (sim GT, display only)"),
        (Circle((0, 0), 1, color=INK), "robot + path (sim GT, display only)"),
    ]
    fig.legend(
        [h for h, _ in items],
        [t for _, t in items],
        loc="upper left" if top else "lower left",
        bbox_to_anchor=(0.005, 0.955) if top else (0.005, 0.0),
        ncol=5 if top else 2,
        frameon=False,
        fontsize=6.5,
        labelcolor=INK2,
        handlelength=1.0,
        columnspacing=1.0,
    )


def draw_camera(ax, view, k: int, dim: bool = False, note: str | None = None) -> None:
    ax.imshow(view["rgb"], alpha=0.35 if dim else 1.0)
    if not dim:
        for conf, x1, y1, x2, y2 in view["dets"]:
            if conf < DV2.tau_absent:  # below it a detection never matters
                continue
            ax.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False, ec=BOX, lw=1.6))
            ax.text(
                x1 + 3,
                y1 - 6,
                f"fire hydrant {conf:.2f}",
                fontsize=6.5,
                color=INK,
                bbox={"fc": BOX, "ec": "none", "pad": 1.2},
            )
    where = "start" if view["target"] < 0 else f"viewpoint #{view['target']}"
    ax.set_title(f"onboard camera, view {k + 1} ({where})", fontsize=8.5, color=INK, loc="left")
    if note:
        ax.text(
            320,
            240,
            note,
            ha="center",
            va="center",
            fontsize=9,
            color=INK,
            bbox={"fc": SURFACE, "ec": GRID, "pad": 6},
        )
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_color(GRID)


def status(view, k: int) -> str:
    n = int(view["cleared"].sum())
    lines = [
        f"decision after {k + 1} view{'s' if k else ''}: {view['decision'].upper()}",
        f"max detector confidence {view['max_conf']:.2f}  (present: >= {DV2.tau_present:.2f})",
        f"seen-through places {n}/64  (absent: 64/64, conf < {DV2.tau_absent:.2f})",
    ]
    if view["scores"]:
        lines.append(pick_text(view["scores"]))
    return "\n".join(lines)


def pick_text(scores) -> str:
    """The policy's pick; a tie (known rule-nbv-v2 limitation, failure analysis) is spelled out."""
    s1, v1 = scores[0]
    tied = [v for s, v in scores if abs(s - s1) < 1e-9]
    if len(tied) > 1:
        return f"next: #{v1} - {len(tied)} candidates tied at {s1:.3f}, lowest id wins"
    return f"next: #{v1} (score {s1:.3f}; runner-up #{scores[1][1]} {scores[1][0]:.3f})"


def frame(spec, gt, views, k, robot, path_xy, dim=False, note=None, title="") -> Image.Image:
    fig = plt.figure(figsize=(9.0, 4.6), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    axm = fig.add_axes([0.0, 0.1, 0.42, 0.82])
    axc = fig.add_axes([0.45, 0.33, 0.53, 0.58])
    axt = fig.add_axes([0.45, 0.02, 0.53, 0.27])
    draw_map(axm, spec, gt, views, k if not dim else k - 1, robot, path_xy)
    draw_camera(axc, views[k] if not dim else views[k - 1], k if not dim else k - 1, dim, note)
    axt.axis("off")
    if not dim:
        axt.text(
            0,
            1,
            status(views[k], k),
            va="top",
            fontsize=7.8,
            color=INK,
            family="monospace",
            linespacing=1.5,
        )
    legend(fig)
    fig.suptitle(title, x=0.01, ha="left", y=0.985, fontsize=9.5, color=INK)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def make_gif(spec, gt, views, out: Path, title: str, motion_frames: int = 14) -> None:
    frames, durations = [], []
    path = np.zeros((0, 2))
    g = views[0]["gt_base"]
    robot = (g["x"], g["y"], g["yaw"])
    frames.append(frame(spec, gt, views, 0, robot, path, title=title))
    durations.append(2600)
    for k in range(1, len(views)):
        tr = views[k]["trace"]
        idx = np.linspace(0, len(tr) - 1, motion_frames).astype(int)
        for j, i in enumerate(idx):
            p = np.vstack([path, tr[: i + 1, 1:3]])
            note = f"Nav2 driving to viewpoint #{views[k]['target']} ..."
            if j == len(idx) - 1 and views[k]["reloc"]:
                rl, sim_s = views[k]["reloc"], views[k]["nav_sim_s"]
                note = (
                    "arrived: stop relocalised against the facility map\n"
                    f"({rl['corrections']} correction(s), {sim_s:.0f} s simulated)"
                )
            frames.append(
                frame(spec, gt, views, k, tuple(tr[i, 1:4]), p, dim=True, note=note, title=title)
            )
            durations.append(1400 if j == len(idx) - 1 else 110)
        path = np.vstack([path, tr[:, 1:3]])
        g = views[k]["gt_base"]
        frames.append(frame(spec, gt, views, k, (g["x"], g["y"], g["yaw"]), path, title=title))
        durations.append(3200 if k < len(views) - 1 else 5000)
    # one shared palette keeps unchanged regions identical between frames (small GIF)
    # (+ swatches of the marker colours, which are too small to survive median cut on their own)
    keys = (SURFACE, INK, INK2, MUTED, GRID, PATH, CLEARED, BOX, WALL, PILLAR, HYDRANT)
    strip = Image.new("RGB", (frames[0].width, frames[0].height * 3 + 60), SURFACE)
    for i, f in enumerate((frames[0], frames[len(frames) // 2], frames[-1])):
        strip.paste(f, (0, i * f.height))
    for i, c in enumerate(keys):
        strip.paste(Image.new("RGB", (60, 60), c), (i * 60, frames[0].height * 3))
    pal = strip.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB, {len(q)} frames)")


def make_storyboard(spec, gt, views, out: Path, title: str) -> None:
    n = len(views)
    fig = plt.figure(figsize=(3.2 * n, 6.6), dpi=170)
    fig.patch.set_facecolor(SURFACE)
    path = np.zeros((0, 2))
    for k, v in enumerate(views):
        if v["trace"] is not None:
            path = np.vstack([path, v["trace"][:, 1:3]])
        g = v["gt_base"]
        axm = fig.add_axes([k / n + 0.005, 0.40, 1 / n - 0.01, 0.50])
        draw_map(axm, spec, gt, views, k, (g["x"], g["y"], g["yaw"]), path)
        axc = fig.add_axes([k / n + 0.01, 0.13, 1 / n - 0.02, 0.26])
        draw_camera(axc, v, k)
        n_cl = int(v["cleared"].sum())
        txt = f"{v['decision'].upper()}\nconf {v['max_conf']:.2f} | seen through {n_cl}/64"
        if v["scores"]:
            txt += "\n" + pick_text(v["scores"])
        fig.text(k / n + 0.012, 0.115, txt, va="top", fontsize=7, color=INK, linespacing=1.4)
    legend(fig, top=True)
    fig.suptitle(title, x=0.01, ha="left", y=0.985, fontsize=10, color=INK)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {out}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/make_demo.py")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--gif")
    ap.add_argument("--png")
    ap.add_argument("--title", help="replaces the generated title")
    args = ap.parse_args(argv)
    run_dir = Path(args.run)
    spec, gt, run = load_run(args.ns, run_dir)
    views = rebuild(spec, run, run_dir)
    title = (
        f"{spec.episode_id} ({gt.state.value}): {POLICY_NAMES[run['policy']]}, Nav2 + TurtleBot 4 "
        f"in Gazebo -> {run['final_decision'].upper()}"
    )
    title = args.title or title
    if args.gif:
        make_gif(spec, gt, views, Path(args.gif), title)
    if args.png:
        make_storyboard(spec, gt, views, Path(args.png), title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
