"""B0 feasibility driver (decision 015). Runs INSIDE the ``inspection-ap-nav`` container.

    python3 -m activeperception.nav.b0_driver prepare --episode nav-b0-g0000-v0 --out runs/nav-b0
    python3 -m activeperception.nav.b0_driver run --episode nav-b0-g0000-v0 --out runs/nav-b0

``prepare`` writes the world, the prior facility map, the mast-camera robot URDF and the Nav2
parameters for one episode. ``run`` (next to ``tb4_simulation_launch.py`` and a
``/gt/odom`` bridge) starts from the initial viewpoint, captures it, then follows
``plan(spec)``: every candidate viewpoint as a Nav2 goal in a seeded order, plus
``N_CANCEL`` goals cancelled part-way, capturing after each stop.

Every capture row keeps the two worlds apart:

- ``deployable``: the AMCL estimate of ``map -> base_link`` and the frame stamps. This is
  all the decision rule may use (``b0_analysis.observation``).
- ``scoring``: ground-truth base pose from ``/gt/odom`` and the semantic labels.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from ..episodes import stable_seed
from ..types import EpisodeSpec
from . import scene

SETTLE_S = 1.0
GOAL_TIMEOUT_S = 120.0
WALL_TIMEOUT_S = 900.0
N_CANCEL = 2
CANCEL_FRACTION = (0.2, 0.8)
NOMINAL_SPEED = 0.5  # m/s, only to time the cancellations (B0 dev run: goals at ~0.4-0.5 m/s)
# Nav2 integration settings (decision 015 section 5, B0 appendix): 0.05 m made the MPPI
# controller dither at the goal ("failed to make progress") in the dev run; AMCL corrects
# more often than the stock 0.25 m / 0.2 rad so the estimate is fresh at each stop.
XY_GOAL_TOLERANCE = 0.07
YAW_GOAL_TOLERANCE = 0.05
AMCL_UPDATE_MIN_D = 0.1
AMCL_UPDATE_MIN_A = 0.1
# nav-relocalize-v1 (decision 016 appendix C): at each candidate, depth-to-map refinement ->
# /initialpose for AMCL -> re-send the goal while outside the Nav2 tolerance (at most twice)
MAX_CORRECTIONS = 2
RELOCALIZE_SIGMA = (0.02, 0.01)  # m, rad
CORRECTION_TIMEOUT_S = 30.0


def plan(spec: EpisodeSpec) -> list[dict]:
    """Seeded visiting order of all candidates with ``N_CANCEL`` cancelled goals inserted.

    A cancelled goal targets one of the three candidates farthest from where the robot is
    expected to be, so the stop lands somewhere off the ring positions.
    """
    rng = np.random.default_rng(stable_seed("nav-b0-plan", spec.episode_id))
    cands = {vp.id: vp for vp in spec.candidate_viewpoints}
    order = [int(i) for i in rng.permutation(sorted(cands))]
    slots = sorted(int(i) for i in rng.choice(np.arange(1, len(order)), N_CANCEL, replace=False))
    steps: list[dict] = []
    here = spec.initial_viewpoint.pose
    for k, vid in enumerate(order):
        if k in slots:
            far = sorted(
                cands,
                key=lambda i: -math.hypot(cands[i].pose.x - here.x, cands[i].pose.y - here.y),
            )[:3]
            steps.append(
                {
                    "kind": "cancel",
                    "target": int(far[int(rng.integers(len(far)))]),
                    "fraction": float(rng.uniform(*CANCEL_FRACTION)),
                }
            )
        steps.append({"kind": "goal", "target": vid})
        here = cands[vid].pose
    return steps


def nav2_overrides(params: dict) -> dict:
    """Integration settings only (decision 015 section 5): arrival tolerance, AMCL cadence."""
    checker = params["controller_server"]["ros__parameters"]["general_goal_checker"]
    checker["xy_goal_tolerance"] = XY_GOAL_TOLERANCE
    checker["yaw_goal_tolerance"] = YAW_GOAL_TOLERANCE
    amcl = params["amcl"]["ros__parameters"]
    amcl["update_min_d"] = AMCL_UPDATE_MIN_D
    amcl["update_min_a"] = AMCL_UPDATE_MIN_A
    return params


def prepare(spec: EpisodeSpec, out: Path) -> None:
    import subprocess

    import yaml
    from ament_index_python.packages import get_package_share_directory

    from .robot import build_urdf
    from .world import nav_world_sdf

    out.mkdir(parents=True, exist_ok=True)
    (out / "world.sdf").write_text(nav_world_sdf(spec))
    pgm, map_yaml = scene.map_files(spec, "map.pgm")
    (out / "map.pgm").write_bytes(pgm)
    (out / "map.yaml").write_text(map_yaml)
    desc = get_package_share_directory("nav2_minimal_tb4_description")
    tb4 = subprocess.run(
        ["xacro", f"{desc}/urdf/standard/turtlebot4.urdf.xacro"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (out / "robot.urdf").write_text(build_urdf(tb4, spec.camera))
    bringup = get_package_share_directory("nav2_bringup")
    params = yaml.safe_load(open(f"{bringup}/params/nav2_params.yaml"))
    (out / "nav2_params.yaml").write_text(yaml.safe_dump(nav2_overrides(params)))
    p = spec.initial_viewpoint.pose
    (out / "launch_args.txt").write_text(f"x_pose:={p.x:.6f} y_pose:={p.y:.6f} yaw:={p.yaw:.6f}\n")


def _yaw(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _rpy(q) -> tuple[float, float, float]:
    roll = math.atan2(2.0 * (q.w * q.x + q.y * q.z), 1.0 - 2.0 * (q.x * q.x + q.y * q.y))
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (q.w * q.y - q.z * q.x))))
    return roll, pitch, _yaw(q)


class Driver:
    def __init__(self, spec: EpisodeSpec, out: Path, relocalize: bool = False):
        import rclpy
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from nav2_simple_commander.robot_navigator import BasicNavigator
        from nav_msgs.msg import Odometry
        from rclpy.parameter import Parameter
        from tf2_ros import Buffer, TransformListener

        from ..sim.gz_client import GzClient

        self.rclpy = rclpy
        self.spec, self.out = spec, out
        self.nav = BasicNavigator()
        self.nav.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.tf = Buffer()
        self._tf_listener = TransformListener(self.tf, self.nav)
        self.gt: dict | None = None
        self.trace: list[tuple[float, float, float, float]] | None = None
        self.amcl: dict | None = None
        self.nav.create_subscription(Odometry, "/gt/odom", self._gt_cb, 50)
        self.nav.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._amcl_cb, 10)
        self.gz = GzClient()
        self.n_caps = 0
        self.relocalize_enabled = relocalize
        self._initial_pub = self.nav.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)

    # -- callbacks (scoring vs deployable kept in separate fields) --
    def _gt_cb(self, msg) -> None:
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        roll, pitch, yaw = _rpy(q)
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self.gt = {"t": t, "x": p.x, "y": p.y, "z": p.z, "roll": roll, "pitch": pitch, "yaw": yaw}
        if self.trace is not None:
            self.trace.append((t, p.x, p.y, yaw))

    def _amcl_cb(self, msg) -> None:
        c = msg.pose.covariance
        self.amcl = {"var_x": c[0], "var_y": c[7], "var_yaw": c[35]}

    # -- helpers --
    def sim_now(self) -> float:
        return self.nav.get_clock().now().nanoseconds * 1e-9

    def spin_sim(self, seconds: float, wall_timeout: float = 60.0) -> None:
        t0, w0 = self.sim_now(), time.monotonic()
        while self.sim_now() < t0 + seconds and time.monotonic() - w0 < wall_timeout:
            self.rclpy.spin_once(self.nav, timeout_sec=0.05)

    def pose_msg(self, x: float, y: float, yaw: float):
        from geometry_msgs.msg import PoseStamped

        p = PoseStamped()
        p.header.frame_id = "map"
        p.header.stamp = self.nav.get_clock().now().to_msg()
        p.pose.position.x, p.pose.position.y = x, y
        p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        return p

    def estimate(self) -> dict:
        """Deployable: the localisation estimate map -> base_link (AMCL + odometry)."""
        from rclpy.time import Time
        from tf2_ros import TransformException

        w0 = time.monotonic()
        while True:
            try:
                tf = self.tf.lookup_transform("map", "base_link", Time())
                break
            except TransformException:  # e.g. right after start-up: buffers not overlapping
                if time.monotonic() - w0 > 30.0:
                    raise
                self.rclpy.spin_once(self.nav, timeout_sec=0.05)
        t = tf.transform.translation
        return {
            "x": t.x,
            "y": t.y,
            "yaw": _yaw(tf.transform.rotation),
            "stamp": tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9,
        }

    def capture(self, tag: str, target: int) -> dict:
        self.spin_sim(SETTLE_S)
        after = self.nav.get_clock().now().nanoseconds
        frames = self.gz.grab(after_ns=after, timeout=60.0)
        self.spin_sim(0.05)
        labels = frames["labels"].array
        if labels.ndim == 3:
            labels = labels[..., 0]
        from ..framestore import encode_depth_mm

        name = f"cap_{self.n_caps:02d}.npz"
        np.savez_compressed(
            self.out / name,
            rgb=frames["rgb"].array,
            depth_mm=encode_depth_mm(frames["depth"].array),
            labels=labels,  # scoring only
        )
        self.n_caps += 1
        self.last_frames = frames  # B1 closed loop reads the capture it just made
        return {
            "tag": tag,
            "target": target,
            "file": name,
            "deployable": {
                "estimate": self.estimate(),
                "amcl_variance": self.amcl,
                "frame_stamps_s": {
                    k: f.stamp_ns * 1e-9 for k, f in frames.items() if k != "labels"
                },
                "capture_after_s": after * 1e-9,
            },
            "scoring": {"gt_base": dict(self.gt) if self.gt else None},
        }

    def publish_initial_pose(self, x: float, y: float, yaw: float) -> None:
        from geometry_msgs.msg import PoseWithCovarianceStamped

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.nav.get_clock().now().to_msg()
        msg.pose.pose = self.pose_msg(x, y, yaw).pose
        sxy, syaw = RELOCALIZE_SIGMA
        cov = [0.0] * 36
        cov[0] = cov[7] = sxy * sxy
        cov[35] = syaw * syaw
        msg.pose.covariance = cov
        self._initial_pub.publish(msg)

    def relocalize(self, vp) -> dict:
        """nav-relocalize-v1: deployable only (AMCL estimate, onboard depth, facility map)."""
        from ..types import Pose
        from .localize import map_outlines, refine_pose
        from .robot import BASE_REST_Z, CAMERA_ABOVE_BASE

        steps, corrections = [], 0
        for k in range(MAX_CORRECTIONS + 1):
            self.spin_sim(SETTLE_S)
            frames = self.gz.grab(after_ns=self.nav.get_clock().now().nanoseconds, timeout=60.0)
            est = self.estimate()
            cam = Pose(
                est["x"], est["y"], BASE_REST_Z + CAMERA_ABOVE_BASE, est["yaw"], scene.MAST_PITCH
            )
            ref = refine_pose(
                frames["depth"].array,
                self.spec.camera,
                cam,
                self.spec.zone,
                map_outlines(self.spec),
            )
            entry = {"refine_ok": ref.ok, "dx": ref.dx, "dy": ref.dy, "dyaw": ref.dyaw}
            steps.append(entry)
            if not ref.ok:
                break
            self.publish_initial_pose(ref.pose.x, ref.pose.y, ref.pose.yaw)
            self.spin_sim(0.5)
            err_xy = math.hypot(ref.pose.x - vp.pose.x, ref.pose.y - vp.pose.y)
            err_yaw = abs((ref.pose.yaw - vp.pose.yaw + math.pi) % (2 * math.pi) - math.pi)
            entry.update({"err_xy": err_xy, "err_yaw": err_yaw})
            if (
                err_xy <= XY_GOAL_TOLERANCE and err_yaw <= YAW_GOAL_TOLERANCE
            ) or k == MAX_CORRECTIONS:
                break
            corrections += 1
            s0 = self.sim_now()
            self.nav.goToPose(self.pose_msg(vp.pose.x, vp.pose.y, vp.pose.yaw))
            while not self.nav.isTaskComplete():
                if self.sim_now() - s0 > CORRECTION_TIMEOUT_S:
                    self.nav.cancelTask()
                    break
            entry["correction_result"] = str(self.nav.getResult()).split(".")[-1]
        return {"corrections": corrections, "steps": steps}

    def navigate(self, step: dict) -> dict:
        vp = {v.id: v for v in self.spec.candidate_viewpoints}[step["target"]]
        here = self.estimate()
        dist = math.hypot(vp.pose.x - here["x"], vp.pose.y - here["y"])
        cancel_at = None
        if step["kind"] == "cancel":
            cancel_at = step["fraction"] * (3.0 + 1.3 * dist / NOMINAL_SPEED)
        self.trace = []
        s0, w0 = self.sim_now(), time.monotonic()
        self.nav.goToPose(self.pose_msg(vp.pose.x, vp.pose.y, vp.pose.yaw))
        canceled = timed_out = wall_out = False
        while not self.nav.isTaskComplete():
            el = self.sim_now() - s0
            if cancel_at is not None and not canceled and el >= cancel_at:
                self.nav.cancelTask()
                canceled = True
            if el > GOAL_TIMEOUT_S and not timed_out:
                self.nav.cancelTask()
                timed_out = True
            if time.monotonic() - w0 > WALL_TIMEOUT_S:
                wall_out = True
                break
        result = str(self.nav.getResult()).split(".")[-1]
        reloc = None
        if self.relocalize_enabled and step["kind"] == "goal" and not wall_out:
            reloc = self.relocalize(vp)
        sim_s, wall_s = self.sim_now() - s0, time.monotonic() - w0
        trace, self.trace = np.array(self.trace or [], dtype=float), None
        tname = f"trace_{self.n_caps:02d}.npy"
        np.save(self.out / tname, trace)  # scoring only (GT path)
        return {
            "result": result,
            "relocalize": reloc,
            "canceled": canceled,
            "timed_out": timed_out,
            "wall_timeout": wall_out,
            "cancel_at_s": cancel_at,
            "sim_s": round(sim_s, 3),
            "wall_s": round(wall_s, 3),
            "rtf": round(sim_s / wall_s, 4) if wall_s > 0 else None,
            "goal": {"x": vp.pose.x, "y": vp.pose.y, "yaw": vp.pose.yaw},
            "trace_file": tname,
        }

    @staticmethod
    def _log(row: dict) -> None:
        est, gt = row["deployable"]["estimate"], row["scoring"]["gt_base"] or {}
        nav = row["nav"] or {}
        print(
            "CAPTURE",
            json.dumps(
                {
                    "tag": row["tag"],
                    "target": row["target"],
                    "result": nav.get("result"),
                    "sim_s": nav.get("sim_s"),
                    "rtf": nav.get("rtf"),
                    "est": [round(est[k], 3) for k in ("x", "y", "yaw")],
                    "gt": [round(gt.get(k, float("nan")), 3) for k in ("x", "y", "z", "yaw")],
                }
            ),
            flush=True,
        )

    def run(self) -> dict:
        p = self.spec.initial_viewpoint.pose
        w0 = time.monotonic()
        self.nav.setInitialPose(self.pose_msg(p.x, p.y, p.yaw))
        self.nav.waitUntilNav2Active()
        active_wall = time.monotonic() - w0
        self.gz.wait_ready(120.0)
        rows = [{"step": None, "nav": None, **self.capture("initial", -1)}]
        self._log(rows[-1])
        for step in plan(self.spec):
            nav = self.navigate(step)
            rows.append({"step": step, "nav": nav, **self.capture(step["kind"], step["target"])})
            self._log(rows[-1])
        return {
            "episode_id": self.spec.episode_id,
            "object_present": self.spec.layout.object_present,  # scoring only
            "relocalize": self.relocalize_enabled,
            "nav2_active_wall_s": round(active_wall, 1),
            "total_wall_s": round(time.monotonic() - w0, 1),
            "rows": rows,
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.nav.b0_driver")
    ap.add_argument("action", choices=["prepare", "run"])
    ap.add_argument("--episode", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--relocalize", action="store_true", help="nav-relocalize-v1 at candidates")
    args = ap.parse_args(argv)
    spec = scene.specs_by_id()[args.episode]
    out = Path(args.out) / spec.episode_id
    if args.action == "prepare":
        prepare(spec, out)
        return 0
    import rclpy

    rclpy.init()
    driver = Driver(spec, out, relocalize=args.relocalize)
    report = driver.run()
    (out / "episode.json").write_text(json.dumps(report, indent=1))
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
