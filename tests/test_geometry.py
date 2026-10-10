import math

import numpy as np

from activeperception.geometry import (
    angular_distance,
    forward_vector,
    look_at_pose,
    project_points,
    segments_blocked,
)
from activeperception.types import Box, CameraModel


def test_look_at_points_forward_to_target():
    pos = np.array([2.0, 1.0, 1.5])
    target = np.array([0.0, 0.0, 0.5])
    pose = look_at_pose(pos, target)
    fwd = forward_vector(pose)
    d = (target - pos) / np.linalg.norm(target - pos)
    assert np.allclose(fwd, d, atol=1e-9)


def test_target_projects_to_image_centre():
    cam = CameraModel()
    pos = np.array([2.0, -1.0, 1.2])
    target = np.array([0.1, 0.2, 0.6])
    pose = look_at_pose(pos, target)
    uv, depth, in_fov = project_points(cam, pose, target[None, :])
    assert in_fov[0]
    assert np.allclose(uv[0], [cam.width / 2, cam.height / 2], atol=1e-6)
    assert math.isclose(depth[0], np.linalg.norm(target - pos))


def test_point_behind_camera_is_out_of_fov():
    cam = CameraModel()
    pose = look_at_pose(np.array([2.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]))
    _, _, in_fov = project_points(cam, pose, np.array([[3.0, 0.0, 1.0]]))
    assert not in_fov[0]


def test_segment_box_intersection_cases():
    box = Box(cx=1.0, cy=0.0, cz=0.5, sx=0.4, sy=0.4, sz=1.0)
    origin = np.array([2.0, 0.0, 0.5])
    targets = np.array(
        [
            [0.0, 0.0, 0.5],  # straight through the box
            [0.0, 1.0, 0.5],  # misses to the side
            [0.0, 0.0, 2.5],  # passes above the box (z=1.3 at the box's near face x=1.2)
            [1.5, 0.0, 0.5],  # stops before the box
        ]
    )
    blocked = segments_blocked(origin, targets, [box])
    assert blocked.tolist() == [True, False, False, False]


def test_segment_parallel_to_axis_inside_slab():
    box = Box(cx=0.0, cy=0.0, cz=0.5, sx=1.0, sy=1.0, sz=1.0)
    # origin inside the box footprint in y and z, moving along x through it
    blocked = segments_blocked(np.array([2.0, 0.0, 0.5]), np.array([[-2.0, 0.0, 0.5]]), [box])
    assert blocked[0]
    # moving along x but offset in y outside the slab -> never hits
    blocked = segments_blocked(np.array([2.0, 3.0, 0.5]), np.array([[-2.0, 3.0, 0.5]]), [box])
    assert not blocked[0]


def test_angular_distance_wraps():
    assert math.isclose(angular_distance(0.1, 2 * math.pi - 0.1), 0.2, abs_tol=1e-12)
    assert math.isclose(angular_distance(0.0, math.pi), math.pi)
