"""API contract tests using FastAPI's in-process test client."""
from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from filecache_sim.api import app, _sessions, _sessions_lock

client = TestClient(app)


def teardown_function() -> None:
    # Each test starts from isolated in-memory simulator state.
    with _sessions_lock:
        _sessions.clear()


def create_simulation(**overrides):
    payload = {
        "capacity_bytes": 64,
        "policy": "lru",
        "workload": "hot_set",
        "request_count": 12,
        "seed": 42,
        "file_count": 8,
        "hot_set_size": 3,
    }
    payload.update(overrides)
    response = client.post("/api/simulations", json=payload)
    return response, payload


def test_health_reports_python_engine_and_simulated_disk():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["engine"] == "filecache_sim.SimulationEngine"
    assert "in-memory" in body["storage"]


def test_create_and_step_exposes_state_and_metrics():
    created, _ = create_simulation()
    assert created.status_code == 201
    simulation_id = created.json()["simulation_id"]

    step = client.post(f"/api/simulations/{simulation_id}/step")
    assert step.status_code == 200
    body = step.json()
    assert body["outcome"]["index"] == 0
    assert body["state"]["next_request_index"] == 1
    assert body["state"]["capacity_bytes"] == 64
    assert body["state"]["metrics"]["requests"] == 1
    assert body["state"]["recency_order_mru_to_lru"] == [
        entry["name"] for entry in body["state"]["cache_entries_mru_to_lru"]
    ]


def test_run_completes_configured_workload_and_state_matches_engine():
    created, payload = create_simulation(policy="adaptive")
    simulation_id = created.json()["simulation_id"]
    run = client.post(f"/api/simulations/{simulation_id}/run")
    assert run.status_code == 200
    state = run.json()
    assert state["status"] == "completed"
    assert state["done"] is True
    assert state["next_request_index"] == payload["request_count"]
    assert state["metrics"]["requests"] == payload["request_count"]
    assert state["policy_diagnostics"]["policy"] == "adaptive_lru"
    assert state["used_bytes"] <= state["capacity_bytes"]
    assert state["used_bytes"] == sum(item["size_bytes"] for item in state["cache_entries_mru_to_lru"])


def test_simulation_sessions_do_not_share_state():
    a, _ = create_simulation(seed=1)
    b, _ = create_simulation(seed=2)
    id_a, id_b = a.json()["simulation_id"], b.json()["simulation_id"]
    client.post(f"/api/simulations/{id_a}/step")
    state_a = client.get(f"/api/simulations/{id_a}/state").json()
    state_b = client.get(f"/api/simulations/{id_b}/state").json()
    assert state_a["next_request_index"] == 1
    assert state_b["next_request_index"] == 0
    assert id_a != id_b


def test_invalid_capacity_policy_and_workload_dimensions_are_rejected():
    bad_capacity, _ = create_simulation(capacity_bytes=0)
    assert bad_capacity.status_code == 422

    bad_policy, _ = create_simulation(policy="not-a-policy")
    assert bad_policy.status_code == 422

    bad_dimensions, _ = create_simulation(file_count=2, hot_set_size=3)
    assert bad_dimensions.status_code == 422

    bad_workload, _ = create_simulation(workload="future-aware")
    assert bad_workload.status_code == 422


def test_unknown_simulation_returns_404():
    assert client.get("/api/simulations/not-real/state").status_code == 404
    assert client.post("/api/simulations/not-real/run").status_code == 404
    assert client.delete("/api/simulations/not-real").status_code == 404


def test_delete_simulation_releases_session():
    created, _ = create_simulation()
    simulation_id = created.json()["simulation_id"]
    deleted = client.delete(f"/api/simulations/{simulation_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"simulation_id": simulation_id, "deleted": True}
    assert client.get(f"/api/simulations/{simulation_id}/state").status_code == 404


def test_export_json_and_csv_are_downloadable():
    created, _ = create_simulation(request_count=5)
    simulation_id = created.json()["simulation_id"]
    client.post(f"/api/simulations/{simulation_id}/run")

    json_response = client.get(f"/api/simulations/{simulation_id}/export?format=json")
    assert json_response.status_code == 200
    payload = json_response.json()
    assert payload["simulation_id"] == simulation_id
    assert len(payload["outcomes"]) == 5

    csv_response = client.get(f"/api/simulations/{simulation_id}/export?format=csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == 5
    assert "hit" in rows[0]
    assert "simulated_storage_seconds" in rows[0]


def test_export_rejects_unknown_format():
    created, _ = create_simulation()
    simulation_id = created.json()["simulation_id"]
    response = client.get(f"/api/simulations/{simulation_id}/export?format=xml")
    assert response.status_code == 422


def test_compare_uses_same_trace_for_both_policies_and_is_seeded():
    payload = {
        "capacity_bytes": 64,
        "workload": "skewed_popularity",
        "request_count": 40,
        "seed": 777,
        "file_count": 10,
        "hot_set_size": 4,
    }
    first = client.post("/api/benchmarks/compare", json=payload)
    second = client.post("/api/benchmarks/compare", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body["same_trace_for_both_policies"] is True
    assert body["trace_fingerprint"] == second.json()["trace_fingerprint"]
    assert body["policies"]["lru"]["outcomes_recorded"] == 40
    assert body["policies"]["adaptive"]["outcomes_recorded"] == 40
    assert body["policies"]["lru"]["metrics"]["requests"] == 40
    assert body["policies"]["adaptive"]["metrics"]["requests"] == 40


def test_benchmark_bounds_and_validation():
    response = client.post("/api/benchmarks/compare", json={
        "capacity_bytes": 64,
        "workload": "hot_set",
        "request_count": 20001,
        "seed": 1,
        "file_count": 10,
        "hot_set_size": 3,
    })
    assert response.status_code == 422


def test_cors_allows_explicit_development_origin():
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    delete_preflight = client.options(
        "/api/simulations/example",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert "DELETE" in delete_preflight.headers.get("access-control-allow-methods", "")
