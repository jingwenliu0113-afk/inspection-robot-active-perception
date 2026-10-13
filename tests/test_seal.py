"""Sealed formal runs stay sealed and their results stay untouched (decision 014)."""

import shutil
from pathlib import Path

import pytest

from activeperception import experiment, experiment_v2, seal
from activeperception.types import Split

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data/episodes/gazebo-core.json"
HOLDOUT = ROOT / "data/episodes/gazebo-holdout.json"
RUNNERS = [(experiment, "test", CORE), (experiment_v2, "holdout", HOLDOUT)]


def test_pinned_files_unchanged():
    assert seal.verify() == []


def test_v1_and_v2_results_and_frozen_configs_are_pinned():
    pins = seal.read_manifest()
    for p in (
        "results/test-v1/report.json",
        "results/test-v1/outcomes.jsonl",
        "results/holdout/report.json",
        "results/holdout/outcomes.jsonl",
        "results/tuning/stage3_val.json",
        "results/tuning-v2/stage2_rule_v2.json",
        "activeperception/frozen.py",
        "activeperception/frozen_v2.py",
        "data/episodes/gazebo-core.json",
        "data/episodes/gazebo-holdout.json",
    ):
        assert p in pins, p


def test_every_committed_result_is_pinned():
    """New result files must be added with ``python -m activeperception.seal manifest``."""
    assert set(seal.pinned_files()) <= set(seal.read_manifest())


def test_sealed_runs_match_by_content_and_split(tmp_path):
    assert seal.sealed_run(CORE, Split.TEST).decision == "010"
    assert seal.sealed_run(HOLDOUT, Split.HOLDOUT).decision == "013"
    # development splits of the same file are not sealed
    assert seal.sealed_run(CORE, Split.VAL) is None
    assert seal.sealed_run(CORE, Split.TRAIN) is None
    # a renamed copy is the same data, so it is still sealed
    copy = tmp_path / "renamed.json"
    shutil.copy(HOLDOUT, copy)
    assert seal.sealed_run(copy, Split.HOLDOUT).decision == "013"


@pytest.mark.parametrize("module,stage,episodes", RUNNERS)
def test_formal_runners_refuse_sealed_runs(module, stage, episodes, tmp_path):
    args = [stage, "--episodes", str(episodes), "--detections", "x", "--out", str(tmp_path / "o")]
    with pytest.raises(SystemExit, match="sealed"):
        module.main(args)
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("module,stage,episodes", RUNNERS)
def test_reproduction_never_writes_under_results(module, stage, episodes):
    out = ROOT / "results" / "reproduction"
    args = [stage, "--episodes", str(episodes), "--detections", "x", "--out", str(out)]
    with pytest.raises(SystemExit, match="never writes under results"):
        module.main([*args, "--reproduce"])
    assert not out.exists()


def test_manifest_refuses_to_repin_a_changed_file(tmp_path, monkeypatch):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "a.json").write_text("{}")
    (tmp_path / seal.MANIFEST).write_text(f"{'0' * 64}  results/a.json\n")
    monkeypatch.setattr(seal, "pinned_files", lambda root: ["results/a.json"])
    with pytest.raises(SystemExit, match="never rewrite"):
        seal.write_manifest(tmp_path)
    assert seal.verify(tmp_path) == ["results/a.json"]
