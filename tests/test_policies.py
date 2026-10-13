from activeperception.grader import grade_all
from activeperception.harness import run_episode_set
from activeperception.metrics import accuracy, false_absent_rate
from activeperception.policies import (
    OracleNBVPolicy,
    RandomNBVPolicy,
    RuleNBVPolicy,
    SingleViewPolicy,
)
from activeperception.types import GroundTruthState


def test_rule_policy_is_deterministic_and_picks_unvisited(world, dev_specs):
    policy = RuleNBVPolicy()
    for spec in dev_specs[:8]:
        dep = spec.deployable()
        hist = [world.observe(spec, spec.initial_viewpoint)]
        policy.reset(dep, 0)
        first = policy.select_next(dep, hist, 4)
        assert first == policy.select_next(dep, hist, 4)
        assert first in {vp.id for vp in dep.candidate_viewpoints}
        hist.append(world.observe(spec, dep.candidate(first)))
        second = policy.select_next(dep, hist, 3)
        assert second not in (first, hist[0].viewpoint_id)


def test_oracle_picks_most_visible_candidate(world, dev_specs, dev_gts):
    policy = OracleNBVPolicy(lambda e: dev_gts[e])
    for spec in dev_specs:
        gt = dev_gts[spec.episode_id]
        if gt.state != GroundTruthState.UNOBSERVABLE:
            continue
        dep = spec.deployable()
        policy.reset(dep, 0)
        pick = policy.select_next(dep, [world.observe(spec, spec.initial_viewpoint)], 4)
        best = max(gt.visibility_by_viewpoint.values())
        assert gt.visibility_by_viewpoint[pick] == best


def test_sanity_ordering_on_synthetic_world(world, rule, dev_specs, dev_gts):
    """Not a research result: a pipeline sanity check that the oracle upper bound
    is not beaten by baselines and that nobody produces false absents here."""
    specs = {s.episode_id: s for s in dev_specs}
    acc = {}
    for policy in (
        SingleViewPolicy(),
        RandomNBVPolicy(),
        RuleNBVPolicy(),
        OracleNBVPolicy(lambda e: dev_gts[e]),
    ):
        recs = run_episode_set(dev_specs, world, policy, rule, 5)
        outs = grade_all(recs, dev_gts, specs)
        acc[policy.name] = accuracy(outs)
        assert false_absent_rate(outs) == 0.0
    assert acc["oracle"] >= acc["random"] >= acc["single"]
    assert acc["oracle"] >= acc["rule"] >= acc["single"]


def test_rule_nbv_v1_coverage_gain_and_visibility_features(world):
    from activeperception.decision import DecisionRuleParams, sector_of
    from activeperception.episodes import generate_episode
    from activeperception.policies import RuleNBVParams, RuleNBVPolicy

    spec = generate_episode("v1feat", 3, 1)
    dep = spec.deployable()
    dp = DecisionRuleParams()
    pol = RuleNBVPolicy(RuleNBVParams(w_coverage=1.0, w_visibility=1.0), dp)
    pol.reset(dep, 0)
    h0 = [world.observe(spec, spec.initial_viewpoint)]
    effective = h0[0].zone_visible_fraction >= dp.effective_zone_fraction
    init_sector = sector_of(spec.initial_viewpoint.azimuth, dp.n_sectors)
    for vp in spec.candidate_viewpoints:
        f = pol.features(dep, h0, vp)
        same = sector_of(vp.azimuth, dp.n_sectors) == init_sector
        assert f["coverage_gain"] == (0.0 if (same and effective) else 1.0)
        assert 0.0 <= f["predicted_visibility"] <= 1.0
    nxt = pol.select_next(dep, h0, 4)
    assert nxt in {vp.id for vp in spec.candidate_viewpoints}
