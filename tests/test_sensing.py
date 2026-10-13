"""Depth / label processing (decision 007) cross-checked against the analytic geometry."""

import math

import numpy as np
import pytest

from activeperception.episodes import build_episode_set, generate_episode
from activeperception.geometry import project_points, ray_cylinder_entry
from activeperception.labeling import LABELING_VERSION, LabelingParams
from activeperception.sensing import (
    gt_visibility_from_labels,
    zone_sample_points,
    zone_visible_fraction_from_depth,
)
from activeperception.sim import SyntheticWorld
from activeperception.sim.raycast import pixel_rays, render_spec
from activeperception.sim.sdf import LABEL_OBJECT
from activeperception.types import CameraModel, InspectionZone, Pose

WORLD = SyntheticWorld()
PROXY = WORLD.params.proxy_radius


def _viewpoints(spec, every=3):
    return [spec.initial_viewpoint, *spec.candidate_viewpoints[::every]]


def test_zone_samples_inside_cylinder():
    z = InspectionZone(1.0, -2.0, 0.4, 0.5, 0.9)
    pts = zone_sample_points(z)
    r = np.hypot(pts[:, 0] - z.cx, pts[:, 1] - z.cy)
    assert len(pts) == 144
    assert (r <= z.radius + 1e-9).all()
    assert ((pts[:, 2] > 0) & (pts[:, 2] < z.height)).all()


def test_ray_cylinder_entry_simple_cases():
    o = np.array([-3.0, 0.0, 0.5])
    d = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 1.0]])
    s = ray_cylinder_entry(o, d, 0.0, 0.0, 1.0, 0.0, 1.0)
    assert s[0] == pytest.approx(2.0)
    assert np.isinf(s[1])
    assert np.isinf(s[2])  # rises above the top before reaching the side
    inside = ray_cylinder_entry(np.zeros(3) + [0, 0, 0.5], d[:1], 0.0, 0.0, 1.0, 0.0, 1.0)
    assert inside[0] == 0.0
    # from above, straight down through the top cap
    top = ray_cylinder_entry(np.array([0.2, 0.0, 3.0]), np.array([[0, 0, -1.0]]), 0, 0, 1, 0, 1)
    assert top[0] == pytest.approx(2.0)


def test_raycast_planar_depth_convention():
    cam = CameraModel()
    pose = Pose(0.0, 0.0, 2.0, yaw=0.0, pitch=math.pi / 2)  # looking straight down
    depth, labels = render_spec(generate_episode("rc", 0, 1), pose, PROXY, clear=True)
    h, w = depth.shape
    # planar depth to a plane parallel to the image is the same at every pixel
    assert np.allclose(depth[np.isfinite(depth)], 2.0, atol=1e-5)
    assert (labels == 30).all()
    origin, dirs = pixel_rays(cam, pose)
    assert np.allclose(origin, [0, 0, 2.0])
    assert dirs.shape == (h * w, 3)


@pytest.mark.parametrize("depth_kind", ["planar", "range"])
def test_depth_zone_visibility_matches_geometry(depth_kind):
    diffs = []
    for spec in build_episode_set("zv", 8)[::2]:
        for vp in _viewpoints(spec):
            depth, _ = render_spec(spec, vp.pose, PROXY)
            if depth_kind == "range":
                _, dirs = pixel_rays(spec.camera, vp.pose)
                depth = depth * np.linalg.norm(dirs, axis=1).reshape(depth.shape)
            got = zone_visible_fraction_from_depth(
                depth, spec.camera, vp.pose, spec.zone, depth_kind=depth_kind
            )
            diffs.append(abs(got - WORLD.zone_visible_fraction(spec, vp)))
    assert max(diffs) <= 0.03, max(diffs)


def test_object_inside_zone_does_not_lower_zone_visibility():
    for g in range(6):
        present, absent = generate_episode("zin", g, 0), generate_episode("zin", g, 1)
        assert present.layout.occluders == absent.layout.occluders
        for vp in _viewpoints(present):
            a = zone_visible_fraction_from_depth(
                render_spec(present, vp.pose, PROXY)[0], present.camera, vp.pose, present.zone
            )
            b = zone_visible_fraction_from_depth(
                render_spec(absent, vp.pose, PROXY)[0], absent.camera, vp.pose, absent.zone
            )
            assert a == b


def test_label_gt_visibility_matches_geometric_gt():
    diffs, agree, n = [], 0, 0
    thr = LabelingParams().visible_min_score
    for spec in build_episode_set("gtv", 10)[::2]:  # present variants only
        for vp in _viewpoints(spec, every=2):
            full = render_spec(spec, vp.pose, PROXY)[1]
            clear = render_spec(spec, vp.pose, PROXY, clear=True)[1]
            lv = gt_visibility_from_labels(full, clear, LABEL_OBJECT)
            geo = WORLD.object_view(spec, vp)["visibility"]
            diffs.append(abs(lv.visibility - geo))
            agree += (lv.visibility >= thr) == (geo >= thr)
            n += 1
    assert np.mean(diffs) < 0.05 and max(diffs) < 0.2, (np.mean(diffs), max(diffs))
    assert agree / n >= 0.95
    assert LABELING_VERSION == "label-v1"


def test_label_gt_edge_cases():
    blank = np.zeros((4, 5), dtype=np.uint8)
    lv = gt_visibility_from_labels(blank, blank, LABEL_OBJECT)
    assert lv.visibility == 0.0 and lv.bbox_full is None
    clear = blank.copy()
    clear[1:3, 1:4] = LABEL_OBJECT
    full = clear.copy()
    full[1:3, 1] = 20  # one column hidden behind a pillar
    lv = gt_visibility_from_labels(full, clear, LABEL_OBJECT)
    assert lv.vis_fraction == pytest.approx(4 / 6)
    assert lv.bbox_full == (1, 1, 4, 3) and lv.bbox_visible == (2, 1, 4, 3)
    assert lv.area_frac == pytest.approx(6 / 20)
    with pytest.raises(ValueError):
        gt_visibility_from_labels(full, clear[:2], LABEL_OBJECT)


def test_depth_shape_and_nan_handling():
    spec = generate_episode("nan", 0, 1)
    vp = spec.candidate_viewpoints[0]
    depth, _ = render_spec(spec, vp.pose, PROXY)
    with pytest.raises(ValueError):
        zone_visible_fraction_from_depth(depth[:10], spec.camera, vp.pose, spec.zone)
    nan = np.full_like(depth, np.nan)  # invalid depth everywhere -> nothing verified visible
    assert zone_visible_fraction_from_depth(nan, spec.camera, vp.pose, spec.zone) == 0.0
    # no return anywhere -> nothing in the way: only the field of view limits visibility
    _, _, in_fov = project_points(spec.camera, vp.pose, zone_sample_points(spec.zone))
    empty = np.full_like(depth, np.inf)
    got = zone_visible_fraction_from_depth(empty, spec.camera, vp.pose, spec.zone)
    assert got == pytest.approx(in_fov.mean())
