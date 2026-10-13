"""Compatibility smoke (decision 015 C1 / C2): stock TurtleBot 4 + Nav2 on Gazebo Harmonic.

Runs INSIDE the ``inspection-ap-nav`` container next to
``ros2 launch nav2_bringup tb4_simulation_launch.py headless:=True use_rviz:=False``.
Sets the initial pose, waits for Nav2 to become active, sends a few goals near the spawn
point of the depot world and records result, wall time, sim time and their ratio.
"""

from __future__ import annotations

import argparse
import json
import math
import time

# the stock spawn (-8, 0) lies outside the bundled depot map (x >= -7.14), so AMCL never
# publishes a pose there; the smoke spawns at START inside the map instead
START = (-6.0, 0.0, 0.0)
GOALS = ((-4.5, 0.0, 0.0), (-4.5, -1.0, -math.pi / 2), (-6.0, 0.0, math.pi))


def main(argv: list[str] | None = None) -> int:
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
    from rclpy.parameter import Parameter

    ap = argparse.ArgumentParser(prog="activeperception.nav.smoke")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rclpy.init()
    nav = BasicNavigator()
    nav.set_parameters([Parameter("use_sim_time", Parameter.Type.BOOL, True)])

    def pose(x: float, y: float, yaw: float) -> PoseStamped:
        p = PoseStamped()
        p.header.frame_id = "map"
        p.header.stamp = nav.get_clock().now().to_msg()
        p.pose.position.x, p.pose.position.y = x, y
        p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        return p

    t_start = time.monotonic()
    nav.setInitialPose(pose(*START))
    nav.waitUntilNav2Active()
    report = {"nav2_active_after_wall_s": round(time.monotonic() - t_start, 1), "goals": []}
    for x, y, yaw in GOALS:
        w0, s0 = time.monotonic(), nav.get_clock().now().nanoseconds
        nav.goToPose(pose(x, y, yaw))
        while not nav.isTaskComplete():
            time.sleep(0.2)
        wall = time.monotonic() - w0
        sim = (nav.get_clock().now().nanoseconds - s0) / 1e9
        report["goals"].append(
            {
                "goal": [x, y, round(yaw, 3)],
                "result": str(nav.getResult()).split(".")[-1],
                "succeeded": nav.getResult() == TaskResult.SUCCEEDED,
                "wall_s": round(wall, 2),
                "sim_s": round(sim, 2),
                "rtf": round(sim / wall, 3) if wall > 0 else None,
            }
        )
        print(report["goals"][-1], flush=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1)
    nav.lifecycleShutdown()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
