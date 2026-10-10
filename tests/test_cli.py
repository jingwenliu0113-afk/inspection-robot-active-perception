import json

from activeperception.cli import main


def test_cli_build_states_run_sweep(tmp_path, capsys):
    ep = tmp_path / "set.json"
    assert main(["build-episodes", "--namespace", "cli", "--groups", "8", "--out", str(ep)]) == 0
    assert main(["states", "--episodes", str(ep)]) == 0
    out = tmp_path / "run"
    assert (
        main(["run", "--episodes", str(ep), "--policy", "rule", "--budget", "3", "--out", str(out)])
        == 0
    )
    assert (out / "records.jsonl").exists() and (out / "metrics.json").exists()
    sweep = tmp_path / "sweep"
    assert (
        main(
            [
                "sweep",
                "--episodes",
                str(ep),
                "--budgets",
                "1,3",
                "--policies",
                "single,oracle",
                "--out",
                str(sweep),
                "--n-boot",
                "20",
            ]
        )
        == 0
    )
    metrics = json.loads((sweep / "metrics.json").read_text())
    assert set(metrics) == {"single@1", "oracle@1", "single@3", "oracle@3"}
    assert "| policy | budget |" in capsys.readouterr().out
