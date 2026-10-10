from activeperception.harness import run_episode_set
from activeperception.policies import RuleNBVPolicy
from activeperception.serialize import load_episode_set, record_from_dict, save_episode_set, to_dict


def test_episode_set_round_trip(tmp_path, dev_specs, dev_gts):
    path = tmp_path / "set.json"
    save_episode_set(path, dev_specs, dev_gts, "synthetic", extra={"note": "t"})
    specs, gts, meta = load_episode_set(path)
    assert specs == dev_specs
    assert gts == dev_gts
    assert meta["world"] == "synthetic" and meta["n_episodes"] == len(dev_specs)


def test_record_round_trip(world, rule, dev_specs):
    recs = run_episode_set(dev_specs[:6], world, RuleNBVPolicy(), rule, 4)
    for r in recs:
        assert record_from_dict(to_dict(r)) == r
