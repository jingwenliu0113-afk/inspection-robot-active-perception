"""Advanced B0 (decision 015): scenes, prior map, robot description, plan, deployable inputs."""

import dataclasses
import inspect
import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from activeperception.nav import b0_analysis, b0_driver, robot, scene, world
from activeperception.nav.b0_analysis import box_distance, camera_pose, deployable_camera_pose
from activeperception.types import Pose, Split

SPECS = scene.b0_specs()


def test_b0_specs_are_dev_only_and_robot_shaped():
    assert len(SPECS) == 12
    assert {s.split for s in SPECS} == {Split.NAV_DEV}
    assert {s.generator_version for s in SPECS} == {"gen-nav-b0"}
    assert [s.layout.object_present for s in SPECS[:2]] == [True, False]
    for s in SPECS:
        for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
            assert vp.radius == pytest.approx(2.0)
            assert vp.pose.z == pytest.approx(1.1)
            assert vp.pose.pitch == pytest.approx(scene.MAST_PITCH)


def test_pillars_leave_room_for_the_robot_at_every_viewpoint():
    for s in SPECS:
        pts = np.array(
            [(v.pose.x, v.pose.y) for v in (s.initial_viewpoint, *s.candidate_viewpoints)]
        )
        for b in s.layout.occluders:
            assert box_distance(pts[:, 0], pts[:, 1], b).min() >= 0.35 - 1e-9
        for w in scene.walls():
            assert box_distance(pts[:, 0], pts[:, 1], w).min() > 1.5


def test_prior_map_never_contains_the_target():
    for present, absent in zip(SPECS[::2], SPECS[1::2], strict=True):
        assert present.layout.object_present and not absent.layout.object_present
        assert (scene.facility_map(present) == scene.facility_map(absent)).all()
    # moving the object does not change the map either
    s = SPECS[0]
    moved = dataclasses.replace(
        s, layout=dataclasses.replace(s.layout, object_pose=Pose(0.2, -0.2, 0.0, 1.0))
    )
    assert (scene.facility_map(s) == scene.facility_map(moved)).all()


def test_prior_map_cells():
    s = SPECS[0]
    occ = scene.facility_map(s)
    n = occ.shape[0]

    def cell(x, y):
        j = int((x + scene.MAP_HALF_M) / scene.MAP_RESOLUTION_M)
        i = int((y + scene.MAP_HALF_M) / scene.MAP_RESOLUTION_M)
        return occ[i, j]

    assert n == 180
    assert cell(0.0, 0.0)  # zone keep-out
    assert cell(4.05, 0.0) and cell(0.0, -4.05)  # walls
    b = s.layout.occluders[0]
    assert cell(b.cx, b.cy)
    vp = s.candidate_viewpoints[0].pose
    assert not cell(vp.x, vp.y)
    pgm, yaml = scene.map_files(s, "map.pgm")
    assert pgm.startswith(b"P5\n180 180\n255\n") and len(pgm) == len(b"P5\n180 180\n255\n") + n * n
    assert "origin: [-4.5, -4.5, 0.0]" in yaml and "resolution: 0.05" in yaml


def test_world_has_walls_and_object_only_when_present():
    for s in SPECS[:2]:
        root = ET.fromstring(world.nav_world_sdf(s))
        names = [m.get("name") for m in root.iter("model")]
        assert sum(n.startswith("wall_") for n in names) == 4
        assert ("target_object" in names) == s.layout.object_present
        assert "inspector_cam" not in names


FAKE_TB4 = """<robot name="turtlebot4"><link name="base_link"/>
<gazebo reference="oakd"><sensor name="rgbd_camera" type="rgbd_camera"/></gazebo>
<gazebo reference="rplidar_link"><sensor name="rplidar" type="gpu_lidar"/></gazebo></robot>"""


def test_robot_gets_mast_camera_and_loses_oakd():
    root = ET.fromstring(robot.build_urdf(FAKE_TB4))
    sensors = {s.get("name"): s for s in root.iter("sensor")}
    assert "rgbd_camera" not in sensors and "rplidar" in sensors
    assert {"inspector_rgb", "inspector_depth", "inspector_segmentation"} <= set(sensors)
    joint = next(j for j in root.iter("joint") if j.get("name") == "inspector_camera_joint")
    xyz = [float(v) for v in joint.find("origin").get("xyz").split()]
    rpy = [float(v) for v in joint.find("origin").get("rpy").split()]
    assert xyz[2] + robot.BASE_REST_Z == pytest.approx(1.1)
    assert rpy[1] == pytest.approx(scene.MAST_PITCH, abs=1e-6)
    plugins = [p.get("name") for p in root.iter("plugin")]
    assert "gz::sim::systems::OdometryPublisher" in plugins
    with pytest.raises(ValueError):
        robot.build_urdf("<robot name='x'><link name='base_link'/></robot>")


def test_plan_visits_every_candidate_once_plus_two_cancelled_goals():
    for s in SPECS[:4]:
        steps = b0_driver.plan(s)
        assert steps == b0_driver.plan(s)  # seeded
        goals = [st["target"] for st in steps if st["kind"] == "goal"]
        cancels = [st for st in steps if st["kind"] == "cancel"]
        assert sorted(goals) == list(range(12))
        assert len(cancels) == b0_driver.N_CANCEL
        assert all(0.2 <= c["fraction"] <= 0.8 for c in cancels)
        assert steps[0]["kind"] == "goal"


def test_nav2_overrides_touch_goal_checker_and_amcl_cadence_only():
    params = {
        "controller_server": {"ros__parameters": {"general_goal_checker": {"a": 1}}},
        "amcl": {"ros__parameters": {"alpha1": 0.2}},
    }
    out = b0_driver.nav2_overrides(params)
    assert out["controller_server"]["ros__parameters"]["general_goal_checker"] == {
        "a": 1,
        "xy_goal_tolerance": 0.07,
        "yaw_goal_tolerance": 0.05,
    }
    assert out["amcl"]["ros__parameters"] == {
        "alpha1": 0.2,
        "update_min_d": 0.1,
        "update_min_a": 0.1,
    }


def test_deployable_inputs_take_no_ground_truth():
    params = set(inspect.signature(b0_analysis.observation).parameters)
    assert params == {"spec", "index", "depth", "dets", "pose"}
    # the deployable camera pose needs only the localisation estimate
    est = {"x": 1.0, "y": -2.0, "yaw": 0.3}
    p = deployable_camera_pose(est)
    assert (p.x, p.y, p.yaw) == pytest.approx((1.0, -2.0, 0.3))
    assert p.z == pytest.approx(1.1) and p.pitch == pytest.approx(scene.MAST_PITCH)


def test_camera_pose_follows_base_tilt():
    level, roll0 = camera_pose(0.0, 0.0, 0.0)
    assert roll0 == pytest.approx(0.0)
    tilted, _ = camera_pose(0.0, 0.0, 0.0, pitch=0.02)
    assert tilted.pitch == pytest.approx(level.pitch + 0.02)
    assert tilted.x == pytest.approx(robot.CAMERA_ABOVE_BASE * math.sin(0.02))


def test_clearance_uses_robot_radius():
    s = SPECS[0]
    b = s.layout.occluders[0]
    x = b.cx + b.sx / 2 + 0.1  # 10 cm from the pillar face: robot body overlaps it
    trace = np.array([[0.0, x, b.cy, 0.0]])
    assert b0_analysis.clearance(trace, s)["obstacle_m"] == pytest.approx(
        0.1 - b0_analysis.ROBOT_RADIUS_M
    )
