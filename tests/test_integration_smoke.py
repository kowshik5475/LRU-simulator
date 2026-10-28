"""Integration-level checks spanning the real engine and FastAPI serialization."""
from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from filecache_sim.api import app, _sessions, _sessions_lock

client = TestClient(app)


def setup_function() -> None:
    with _sessions_lock:
        _sessions.clear()


def teardown_function() -> None:
    with _sessions_lock:
        _sessions.clear()


def test_step_state_refresh_and_exports_match_observed_engine_outcomes():
    created = client.post("/api/simulations", json={
        "capacity_bytes": 32,
        "policy": "adaptive",
        "workload": "mixed_sizes_io",
        "request_count": 8,
        "seed": 123,
        "file_count": 6,
        "hot_set_size": 2,
    })
    assert created.status_code == 201, created.text
    simulation_id = created.json()["simulation_id"]

    first_step = client.post(f"/api/simulations/{simulation_id}/step")
    assert first_step.status_code == 200, first_step.text
    outcome = first_step.json()["outcome"]
    refreshed = client.get(f"/api/simulations/{simulation_id}/state")
    assert refreshed.status_code == 200
    state = refreshed.json()
    assert state["next_request_index"] == 1
    assert state["last_outcome"]["index"] == outcome["index"]
    assert state["metrics"]["requests"] == 1
    assert state["used_bytes"] == sum(entry["size_bytes"] for entry in state["cache_entries_mru_to_lru"])
    assert state["recency_order_mru_to_lru"] == [
        entry["name"] for entry in state["cache_entries_mru_to_lru"]
    ]

    run = client.post(f"/api/simulations/{simulation_id}/run")
    assert run.status_code == 200, run.text
    final_state = run.json()
    assert final_state["done"] is True
    assert final_state["metrics"]["requests"] == 8
    assert final_state["used_bytes"] <= final_state["capacity_bytes"]

    json_response = client.get(f"/api/simulations/{simulation_id}/export?format=json")
    assert json_response.status_code == 200
    exported = json_response.json()
    assert len(exported["outcomes"]) == final_state["metrics"]["requests"]
    assert exported["metrics"] == final_state["metrics"]
    assert "attachment;" in json_response.headers["content-disposition"]

    csv_response = client.get(f"/api/simulations/{simulation_id}/export?format=csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == len(exported["outcomes"])
    assert rows[-1]["index"] == str(len(rows) - 1)


def test_benchmark_same_configuration_reproduces_trace_and_deterministic_metrics():
    request = {
        "capacity_bytes": 48,
        "workload": "changing_hot_set",
        "request_count": 60,
        "seed": 9001,
        "file_count": 12,
        "hot_set_size": 3,
        "read_latency_seconds": 0.005,
        "write_latency_seconds": 0.01,
        "read_cost": 1,
        "write_cost": 2,
    }
    first = client.post("/api/benchmarks/compare", json=request)
    second = client.post("/api/benchmarks/compare", json=request)
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["trace_fingerprint"] == b["trace_fingerprint"]
    assert a["same_trace_for_both_policies"] is True
    assert b["same_trace_for_both_policies"] is True
    assert a["policies"].keys() == b["policies"].keys()
    for policy in ("lru", "adaptive"):
        assert a["policies"][policy]["metrics"] | {} == {
            **b["policies"][policy]["metrics"],
            "actual_execution_seconds": a["policies"][policy]["metrics"]["actual_execution_seconds"],
        }
        assert a["policies"][policy]["final_cache_keys_mru_to_lru"] == b["policies"][policy]["final_cache_keys_mru_to_lru"]
        assert a["policies"][policy]["outcomes_recorded"] == 60


def test_api_rejects_extra_fields_and_invalid_workload_dimensions():
    payload = {
        "capacity_bytes": 32, "policy": "lru", "workload": "hot_set",
        "request_count": 3, "seed": 1, "file_count": 2, "hot_set_size": 1,
        "surprise": True,
    }
    assert client.post("/api/simulations", json=payload).status_code == 422
    payload.pop("surprise")
    payload["hot_set_size"] = 3
    assert client.post("/api/simulations", json=payload).status_code == 422
