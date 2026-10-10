import math

from activeperception.decision import DecisionRule, DecisionRuleParams
from activeperception.episodes import generate_episode
from activeperception.types import Decision, Detection, Observation, Pose, Viewpoint


def _vp(i, az):
    return Viewpoint(
        id=i,
        pose=Pose(2 * math.cos(az), 2 * math.sin(az), 1.0, az + math.pi),
        azimuth=az,
        radius=2.0,
        height=1.0,
    )


def _obs(i, az, conf=None, zone=1.0):
    dets = () if conf is None else (Detection(conf, (0, 0, 10, 10), 0.001, (0.5, 0.5)),)
    return Observation(
        viewpoint_id=i,
        viewpoint=_vp(i, az),
        detections=dets,
        zone_visible_fraction=zone,
        timestamp=0.0,
    )


def test_no_detection_single_view_is_inconclusive_not_absent():
    rule = DecisionRule()
    dep = generate_episode("dec", 0, 0).deployable()
    out = rule.decide(dep, [_obs(-1, 0.0)])
    assert out.decision == Decision.INCONCLUSIVE


def test_strong_detection_is_present():
    rule = DecisionRule()
    dep = generate_episode("dec", 0, 0).deployable()
    out = rule.decide(dep, [_obs(-1, 0.0, conf=0.9)])
    assert out.decision == Decision.PRESENT
    assert out.confidence == 0.9


def test_absent_requires_coverage_of_unblocked_views():
    rule = DecisionRule(DecisionRuleParams(n_sectors=6, min_coverage=0.5))
    dep = generate_episode("dec", 0, 0).deployable()
    step = 2 * math.pi / 6
    three = [_obs(-1, 0.1), _obs(0, 0.1 + step), _obs(1, 0.1 + 2 * step)]
    assert rule.decide(dep, three).decision == Decision.ABSENT
    # same bearings but blocked views do not count towards coverage
    blocked = [_obs(-1, 0.1), _obs(0, 0.1 + step, zone=0.1), _obs(1, 0.1 + 2 * step)]
    assert rule.decide(dep, blocked).decision == Decision.INCONCLUSIVE
    # three views in the same sector do not count as coverage either
    same = [_obs(-1, 0.1), _obs(0, 0.15), _obs(1, 0.2)]
    assert rule.decide(dep, same).decision == Decision.INCONCLUSIVE


def test_weak_detection_blocks_absent():
    rule = DecisionRule(DecisionRuleParams(n_sectors=6, min_coverage=0.5, tau_absent=0.3))
    dep = generate_episode("dec", 0, 0).deployable()
    step = 2 * math.pi / 6
    hist = [_obs(-1, 0.1, conf=0.4), _obs(0, 0.1 + step), _obs(1, 0.1 + 2 * step)]
    assert rule.decide(dep, hist).decision == Decision.INCONCLUSIVE
