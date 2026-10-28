import pytest

from filecache_sim.cli import main


def test_demo_runs(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "[EVICT] app.log" in out
    assert "Hit ratio" in out


def test_invalid_capacity():
    with pytest.raises(SystemExit):
        main(["demo", "-c", "0"])


def test_adaptive_policy_can_be_selected_from_cli(capsys):
    assert main(["demo", "--policy", "adaptive", "-c", "120"]) == 0
    out = capsys.readouterr().out
    assert "File Cache Demo: adaptive" in out
    assert "Policy diagnostics:" in out
    assert "'policy': 'adaptive_lru'" in out
