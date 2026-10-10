import math
import xml.etree.ElementTree as ET

from activeperception.episodes import generate_episode
from activeperception.geometry import rotation_matrix
from activeperception.sim.sdf import (
    CAMERA_MODEL,
    OBJECT_MODEL,
    PILLAR_PREFIX,
    WORLD_NAME,
    main,
    pose_to_sdf,
    set_pose_request,
    validate,
    world_sdf,
)
from activeperception.types import Pose


def _models(root):
    return {m.get("name"): m for m in root.iter("model")}


def test_world_is_well_formed_and_matches_layout():
    for variant in (0, 1):
        spec = generate_episode("sdf", 3, variant)
        root = validate(world_sdf(spec))
        world = root.find("world")
        assert world.get("name") == WORLD_NAME
        models = _models(root)
        assert (OBJECT_MODEL in models) == spec.layout.object_present
        pillars = [n for n in models if n.startswith(PILLAR_PREFIX)]
        assert len(pillars) == len(spec.layout.occluders)
        assert CAMERA_MODEL in models and "ground_plane" in models


def test_camera_sensors_share_intrinsics_and_initial_pose():
    spec = generate_episode("sdf", 1, 0)
    root = validate(world_sdf(spec))
    cam = _models(root)[CAMERA_MODEL]
    assert cam.find("pose").text == pose_to_sdf(spec.initial_viewpoint.pose)
    sensors = {s.get("type") for s in cam.iter("sensor")}
    assert sensors == {"camera", "depth_camera", "segmentation_camera"}
    for s in cam.iter("sensor"):
        c = s.find("camera")
        assert math.isclose(float(c.find("horizontal_fov").text), spec.camera.hfov, abs_tol=1e-6)
        assert int(c.find("image/width").text) == spec.camera.width
        assert int(c.find("image/height").text) == spec.camera.height


def test_required_world_plugins_present():
    root = validate(world_sdf(generate_episode("sdf", 0, 0)))
    names = {p.get("name") for p in root.find("world").findall("plugin")}
    assert {
        "gz::sim::systems::Sensors",
        "gz::sim::systems::UserCommands",
        "gz::sim::systems::Physics",
    } <= names


def test_pose_to_sdf_roundtrip_convention():
    pose = Pose(1.0, -2.0, 1.5, yaw=0.7, pitch=0.2)
    assert pose_to_sdf(pose).split() == [
        "1.000000",
        "-2.000000",
        "1.500000",
        "0",
        "0.200000",
        "0.700000",
    ]


def test_set_pose_quaternion_matches_rotation_matrix():
    pose = Pose(0.5, 0.25, 1.0, yaw=-1.1, pitch=0.35)
    req = set_pose_request(pose)
    q = {
        k: float(v)
        for k, v in (
            kv.split(": ") for kv in req.split("orientation: {")[1].rstrip("}").split(", ")
        )
    }
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    # quaternion -> rotation matrix
    r = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    expected = rotation_matrix(pose.yaw, pose.pitch)
    for i in range(3):
        for j in range(3):
            assert math.isclose(
                r[i][j], expected[i][j], abs_tol=1e-5
            )  # request text has 6 decimals
    assert f'name: "{CAMERA_MODEL}"' in req


def test_cli_writes_file(tmp_path):
    out = tmp_path / "w.sdf"
    assert main(["--namespace", "pilot", "--group", "0", "--variant", "0", "--out", str(out)]) == 0
    ET.parse(out)
