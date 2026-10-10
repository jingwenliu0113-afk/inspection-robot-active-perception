import dataclasses

from activeperception.episodes import GeneratorConfig, build_episode_set, generate_episode
from activeperception.sim import SyntheticWorld
from activeperception.types import GroundTruthState


def test_three_states_all_occur(world, dev_specs, dev_gts):
    states = {gt.state for gt in dev_gts.values()}
    assert states == set(GroundTruthState)


def test_absent_iff_object_absent(dev_specs, dev_gts):
    for s in dev_specs:
        gt = dev_gts[s.episode_id]
        assert gt.object_present == s.layout.object_present
        assert (gt.state == GroundTruthState.ABSENT) == (not s.layout.object_present)
        assert gt.visibility_initial == 0.0 or s.layout.object_present


def test_blocking_initial_view_produces_unobservable():
    cfg = dataclasses.replace(GeneratorConfig(), p_block_initial=1.0, n_occluders_range=(1, 1))
    world = SyntheticWorld()
    n_unobs = 0
    for g in range(10):
        gt = world.ground_truth(generate_episode("blk", g, 0, cfg))
        n_unobs += gt.state == GroundTruthState.UNOBSERVABLE
    assert n_unobs >= 8


def test_no_occluders_means_visible():
    cfg = dataclasses.replace(GeneratorConfig(), n_occluders_range=(0, 0), p_block_initial=0.0)
    world = SyntheticWorld()
    for g in range(10):
        gt = world.ground_truth(generate_episode("clear", g, 0, cfg))
        assert gt.state == GroundTruthState.VISIBLE
        assert gt.visibility_initial > 0.9


def test_observation_is_memoryless_and_deterministic(world):
    spec = generate_episode("tele", 2, 0)
    a = [world.observe(spec, vp) for vp in spec.candidate_viewpoints]
    b = [world.observe(spec, vp) for vp in reversed(spec.candidate_viewpoints)][::-1]
    assert a == b
    assert world.observe(spec, spec.initial_viewpoint) == world.observe(
        spec, spec.initial_viewpoint
    )


def test_absent_object_yields_no_strong_detection(world):
    for s in build_episode_set("absent", 15):
        if s.layout.object_present:
            continue
        for vp in (s.initial_viewpoint, *s.candidate_viewpoints):
            obs = world.observe(s, vp)
            assert obs.max_confidence < 0.5


def test_visible_initial_gives_strong_detection(world, dev_specs, dev_gts):
    for s in dev_specs:
        gt = dev_gts[s.episode_id]
        if gt.state == GroundTruthState.VISIBLE and gt.visibility_initial > 0.9:
            assert world.observe(s, s.initial_viewpoint).max_confidence > 0.6
