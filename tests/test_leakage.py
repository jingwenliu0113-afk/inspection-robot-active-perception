"""Candidate viewpoints and deployable policies must not depend on ground truth."""

import dataclasses

import pytest

from activeperception.decision import DecisionRule
from activeperception.episodes import GeneratorConfig, candidate_viewpoints, generate_episode
from activeperception.harness import run_episode
from activeperception.policies import RandomNBVPolicy, RuleNBVPolicy, SingleViewPolicy
from activeperception.sim import SyntheticWorld
from activeperception.types import DeployableEpisode


def test_candidates_identical_across_variants_of_a_group():
    cfg = GeneratorConfig()
    variants = [generate_episode("leak", 5, v, cfg) for v in range(cfg.variants_per_group)]
    present = {v.layout.object_present for v in variants}
    assert present == {True, False}
    for v in variants[1:]:
        assert v.candidate_viewpoints == variants[0].candidate_viewpoints
        assert v.initial_viewpoint == variants[0].initial_viewpoint


def test_candidates_are_a_function_of_group_seed_only():
    cfg = GeneratorConfig()
    s = generate_episode("leak", 9, 2, cfg)
    assert s.candidate_viewpoints == candidate_viewpoints("leak", 9, cfg)
    # changing object / occluder config must not change the candidate set
    cfg2 = dataclasses.replace(
        cfg, object_radius=0.3, n_occluders_range=(3, 3), p_block_initial=1.0
    )
    s2 = generate_episode("leak", 9, 2, cfg2)
    assert s2.layout != s.layout
    assert s2.candidate_viewpoints == s.candidate_viewpoints
    assert s2.initial_viewpoint == s.initial_viewpoint


def test_deployable_view_carries_no_scene_layout():
    s = generate_episode("leak", 1, 0)
    dep = s.deployable()
    names = {f.name for f in dataclasses.fields(DeployableEpisode)}
    assert names == {"episode_id", "zone", "camera", "initial_viewpoint", "candidate_viewpoints"}
    assert not hasattr(dep, "layout")
    assert "object" not in repr(dep).lower()


class TripwireWorld(SyntheticWorld):
    """Raises if anything asks for ground truth during a deployable run."""

    def ground_truth(self, spec):
        raise AssertionError("ground truth accessed during a deployable policy run")


@pytest.mark.parametrize("policy", [SingleViewPolicy(), RandomNBVPolicy(), RuleNBVPolicy()])
def test_deployable_policies_never_touch_ground_truth(policy):
    world = TripwireWorld()
    rule = DecisionRule()
    for g in range(6):
        for v in range(4):
            spec = generate_episode("trip", g, v)
            run_episode(spec, world, policy, rule, budget=5)
    assert not hasattr(policy, "_gt_lookup")
