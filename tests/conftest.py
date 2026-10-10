import pytest

from activeperception.decision import DecisionRule
from activeperception.episodes import GeneratorConfig, build_episode_set
from activeperception.sim import SyntheticWorld


@pytest.fixture(scope="session")
def world():
    return SyntheticWorld()


@pytest.fixture(scope="session")
def dev_specs():
    return build_episode_set("test-fixture", 30, GeneratorConfig())


@pytest.fixture(scope="session")
def dev_gts(world, dev_specs):
    return {s.episode_id: world.ground_truth(s) for s in dev_specs}


@pytest.fixture(scope="session")
def rule():
    return DecisionRule()
