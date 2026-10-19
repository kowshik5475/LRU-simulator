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
