import math
from collections import Counter

import numpy as np

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
