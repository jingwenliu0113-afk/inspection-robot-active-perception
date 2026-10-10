import pytest

from activeperception.harness import HarnessError, run_episode, run_episode_set
from activeperception.policies import (
    OracleNBVPolicy,
    RandomNBVPolicy,
    RuleNBVPolicy,
    SingleViewPolicy,
)
from activeperception.types import INITIAL_VIEWPOINT_ID, Decision


def _policies(gts):
    return [
        SingleViewPolicy(),
        RandomNBVPolicy(),
        RuleNBVPolicy(),
        OracleNBVPolicy(lambda e: gts[e]),
    ]


@pytest.mark.parametrize("budget", [1, 2, 3, 5, 8])
def test_budget_never_exceeded_initial_first_no_revisit(world, rule, dev_specs, dev_gts, budget):
    for policy in _policies(dev_gts):
        for rec in run_episode_set(dev_specs, world, policy, rule, budget):
            assert 1 <= rec.viewpoints_used <= budget
            assert rec.viewpoint_sequence[0] == INITIAL_VIEWPOINT_ID
            assert len(set(rec.viewpoint_sequence)) == len(rec.viewpoint_sequence)


def test_budget_one_makes_every_policy_single_view(world, rule, dev_specs, dev_gts):
    base = run_episode_set(dev_specs, world, SingleViewPolicy(), rule, 1)
    for policy in _policies(dev_gts)[1:]:
        recs = run_episode_set(dev_specs, world, policy, rule, 1)
        assert [(r.decision, r.viewpoint_sequence) for r in recs] == [
            (r.decision, r.viewpoint_sequence) for r in base
        ]


def test_runs_are_reproducible(world, rule, dev_specs, dev_gts):
    for policy in _policies(dev_gts):
        a = run_episode_set(dev_specs, world, policy, rule, 4, run_seed=3)
        b = run_episode_set(dev_specs, world, policy, rule, 4, run_seed=3)
        assert a == b


def test_random_policy_depends_on_run_seed(world, rule, dev_specs):
    a = run_episode_set(dev_specs, world, RandomNBVPolicy(), rule, 5, run_seed=1)
    b = run_episode_set(dev_specs, world, RandomNBVPolicy(), rule, 5, run_seed=2)
    assert [r.viewpoint_sequence for r in a] != [r.viewpoint_sequence for r in b]


def test_stops_once_decision_is_definitive(world, rule, dev_specs):
    for rec in run_episode_set(dev_specs, world, RuleNBVPolicy(), rule, 6):
        # every observation before the last one must have left the rule inconclusive
        for k in range(1, rec.viewpoints_used):
            partial = rule.decide(dev_specs[0].deployable(), rec.observations[:k])
            assert partial.decision == Decision.INCONCLUSIVE
        if rec.viewpoints_used < 6 and rec.decision == Decision.INCONCLUSIVE:
            pytest.fail("stopped early while inconclusive with budget left")


class RevisitPolicy:
    name = "bad-revisit"

    def reset(self, episode, run_seed):
        pass

    def select_next(self, episode, history, remaining):
        return history[-1].viewpoint_id if len(history) > 1 else episode.candidate_viewpoints[0].id


class UnknownIdPolicy:
    name = "bad-unknown"

    def reset(self, episode, run_seed):
        pass

    def select_next(self, episode, history, remaining):
        return 999


def test_harness_rejects_revisits_and_unknown_ids(world, rule, dev_specs):
    spec = next(s for s in dev_specs if not s.layout.object_present)
    with pytest.raises(HarnessError):
        run_episode(spec, world, RevisitPolicy(), rule, budget=6)
    with pytest.raises(HarnessError):
        run_episode(spec, world, UnknownIdPolicy(), rule, budget=3)


def test_budget_must_be_positive(world, rule, dev_specs):
    with pytest.raises(ValueError):
        run_episode(dev_specs[0], world, SingleViewPolicy(), rule, budget=0)
