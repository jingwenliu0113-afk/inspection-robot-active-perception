import math
from collections import Counter

import numpy as np
import pytest

from activeperception.episodes import (
    PILOT_NAMESPACE,
    GeneratorConfig,
    build_episode_set,
    candidate_viewpoints,
    generate_episode,
    split_for_group,
)
from activeperception.geometry import forward_vector
from activeperception.types import INITIAL_VIEWPOINT_ID, Split


def test_generation_is_deterministic():
    a = build_episode_set("det", 6)
    b = build_episode_set("det", 6)
    assert a == b


def test_episode_ids_unique_and_formatted():
    specs = build_episode_set("ids", 5)
    ids = [s.episode_id for s in specs]
    assert len(ids) == len(set(ids)) == 20
    assert ids[0] == "ids-g0000-v0"


def test_variants_alternate_present_absent():
    for s in build_episode_set("pa", 4):
        assert s.layout.object_present == (s.variant % 2 == 0)
        assert (s.layout.object_pose is None) == (not s.layout.object_present)


def test_object_inside_zone():
    for s in build_episode_set("zone", 20):
        if s.layout.object_pose is not None:
            p = s.layout.object_pose
            d = math.hypot(p.x - s.zone.cx, p.y - s.zone.cy)
            assert d + s.layout.object_radius <= s.zone.radius + 1e-9


def test_viewpoints_look_at_zone_centre():
    s = generate_episode("look", 3, 0)
    for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
        fwd = forward_vector(vp.pose)
        to_zone = np.array([s.zone.cx, s.zone.cy, s.zone.cz]) - np.array(vp.pose.position())
        to_zone /= np.linalg.norm(to_zone)
        assert np.dot(fwd, to_zone) > 0.9999


def test_viewpoint_ids():
    s = generate_episode("ids2", 0, 0)
    assert s.initial_viewpoint.id == INITIAL_VIEWPOINT_ID
    assert [vp.id for vp in s.candidate_viewpoints] == list(range(12))


def test_split_is_per_scene_group_and_balanced():
    cfg = GeneratorConfig()
    specs = build_episode_set("split", 300, cfg)
    by_group = {}
    for s in specs:
        by_group.setdefault(s.scene_group, set()).add(s.split)
    assert all(len(v) == 1 for v in by_group.values()), "a scene group straddles splits"
    counts = Counter(next(iter(v)) for v in by_group.values())
    frac = {k: counts[k] / 300 for k in counts}
    assert abs(frac[Split.TRAIN] - 0.4) < 0.08
    assert abs(frac[Split.VAL] - 0.2) < 0.08
    assert abs(frac[Split.TEST] - 0.4) < 0.08
    assert Split.PILOT not in counts


def test_pilot_namespace_is_disjoint():
    cfg = GeneratorConfig()
    assert split_for_group(PILOT_NAMESPACE, 7, cfg) == Split.PILOT
    pilot = generate_episode(PILOT_NAMESPACE, 7, 0, cfg)
    formal = generate_episode("formal", 7, 0, cfg)
    assert pilot.split == Split.PILOT
    assert pilot.seed != formal.seed
    assert pilot.candidate_viewpoints != formal.candidate_viewpoints
    assert candidate_viewpoints(PILOT_NAMESPACE, 7, cfg) != candidate_viewpoints("formal", 7, cfg)


def test_different_groups_differ():
    a = generate_episode("diff", 0, 0)
    b = generate_episode("diff", 1, 0)
    assert a.candidate_viewpoints != b.candidate_viewpoints
    assert a.layout != b.layout


def _footprint_distance_range(box, cx, cy):
    """Min / max distance from (cx, cy) to the four corners and the box centre."""
    corners = [
        (box.cx + sx * box.sx / 2, box.cy + sy * box.sy / 2) for sx in (-1, 1) for sy in (-1, 1)
    ]
    ds = [math.hypot(x - cx, y - cy) for x, y in corners]
    # the closest point of an axis-aligned square can be on an edge, not a corner
    nx = min(max(cx, box.cx - box.sx / 2), box.cx + box.sx / 2)
    ny = min(max(cy, box.cy - box.sy / 2), box.cy + box.sy / 2)
    return math.hypot(nx - cx, ny - cy), max(ds)


def test_pillars_stay_out_of_zone_and_off_the_camera_ring():
    cfg = GeneratorConfig()
    for s in build_episode_set("pillars", 60, cfg):
        for box in s.layout.occluders:
            near, far = _footprint_distance_range(box, s.zone.cx, s.zone.cy)
            assert near >= s.zone.radius + cfg.occluder_zone_clearance - 1e-9
            for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
                assert far < math.hypot(vp.pose.x - s.zone.cx, vp.pose.y - s.zone.cy)
            assert box.cz == box.sz / 2  # standing on the ground


def test_object_stands_on_ground_inside_zone():
    for s in build_episode_set("ground", 20):
        p = s.layout.object_pose
        if p is None:
            continue
        assert p.z == 0.0 and 0.0 <= p.yaw < 2 * math.pi
        assert s.layout.object_height <= s.zone.height
        assert s.layout.object_model == "fire_hydrant"


def test_present_absent_pairs_share_occluders():
    for g in range(10):
        v = [generate_episode("pairs", g, k) for k in range(4)]
        assert v[0].layout.occluders == v[1].layout.occluders
        assert v[2].layout.occluders == v[3].layout.occluders
        assert [b.sz for b in v[0].layout.occluders] == [b.sz for b in v[2].layout.occluders]
        assert v[0].layout.object_present and not v[1].layout.object_present
        assert v[2].layout.object_present and not v[3].layout.object_present


def test_detsel_namespace_is_its_own_split():
    from activeperception.episodes import DETSEL_NAMESPACE

    specs = build_episode_set(DETSEL_NAMESPACE, 20)
    assert {s.split for s in specs} == {Split.DETSEL}


def test_holdout_namespace_is_its_own_split():
    from activeperception.episodes import HOLDOUT_NAMESPACE

    specs = build_episode_set(HOLDOUT_NAMESPACE, 20)
    assert {s.split for s in specs} == {Split.HOLDOUT}
    core = build_episode_set("core", 20)
    assert {s.seed for s in specs}.isdisjoint({s.seed for s in core})


MAX_ULP = 4  # Linux (glibc) and macOS libm sin / cos differ by <= 3 ulp on these specs


def _same_within_ulp(a, b, path="") -> None:
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), path
        for k in a:
            _same_within_ulp(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _same_within_ulp(x, y, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert abs(a - b) <= MAX_ULP * math.ulp(max(abs(a), abs(b), 1e-300)), (path, a, b)
    else:
        assert a == b, (path, a, b)


@pytest.mark.parametrize("namespace,groups", [("core", 300), ("holdout", 150), ("nav-b2", 40)])
def test_committed_specs_regenerate(tmp_path, namespace, groups):
    """The seeded generators reproduce the committed (sealed) spec files. They were generated on
    macOS arm64, where the bytes are identical; elsewhere the platform's libm may round sin / cos
    differently in the last bits, so floats must agree within a few ulp, everything else exactly."""
    import json
    import platform
    import sys
    from pathlib import Path

    from activeperception import cli
    from activeperception.nav import scene

    out = tmp_path / "specs.json"
    args = ["--namespace", namespace, "--groups", str(groups), "--out", str(out)]
    if namespace.startswith("nav-"):
        scene.main(args)
    else:
        cli.main(["make-specs", *args])
    committed = Path(__file__).resolve().parents[1] / "data/episodes" / f"specs-{namespace}.json"
    if sys.platform == "darwin" and platform.machine() == "arm64":
        assert out.read_bytes() == committed.read_bytes()
    else:
        _same_within_ulp(json.loads(committed.read_text()), json.loads(out.read_text()))
