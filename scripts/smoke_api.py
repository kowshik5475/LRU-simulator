"""Small live HTTP smoke test against the actual FastAPI app and Python engine.

Run from the repository root with: python scripts/smoke_api.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reserve_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(base: str, path: str, *, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def main() -> int:
    port = reserve_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "filecache_sim.api:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(80):
            if server.poll() is not None:
                raise RuntimeError(f"uvicorn exited early with status {server.returncode}")
            try:
                status, _, body = request(base, "/api/health")
                if status == 200:
                    break
            except (OSError, TimeoutError):
                time.sleep(0.15)
        else:
            raise RuntimeError("FastAPI server did not become ready")

        health = json.loads(body)
        assert health["engine"] == "filecache_sim.SimulationEngine"

        config = {
            "capacity_bytes": 48, "policy": "adaptive",
            "workload": "mixed_sizes_io", "request_count": 12,
            "seed": 4242, "file_count": 8, "hot_set_size": 3,
        }
        status, _, body = request(base, "/api/simulations", method="POST", payload=config)
        assert status == 201, body.decode()
        simulation_id = json.loads(body)["simulation_id"]

        status, _, body = request(base, f"/api/simulations/{simulation_id}/step", method="POST")
        assert status == 200
        step = json.loads(body)
        assert step["state"]["next_request_index"] == 1

        status, _, body = request(base, f"/api/simulations/{simulation_id}/state")
        assert status == 200
        refreshed = json.loads(body)
        assert refreshed["next_request_index"] == 1
        assert refreshed["metrics"]["requests"] == 1

        status, _, body = request(base, f"/api/simulations/{simulation_id}/run", method="POST")
        assert status == 200
        final = json.loads(body)
        assert final["done"] and final["metrics"]["requests"] == config["request_count"]
        assert final["used_bytes"] <= final["capacity_bytes"]

        status, headers, body = request(base, f"/api/simulations/{simulation_id}/export?format=json")
        assert status == 200 and "attachment;" in headers.get("Content-Disposition", "")
        exported = json.loads(body)
        assert len(exported["outcomes"]) == config["request_count"]
        assert exported["metrics"] == final["metrics"]

        status, _, body = request(base, f"/api/simulations/{simulation_id}/export?format=csv")
        assert status == 200 and len(body.decode("utf-8").splitlines()) == config["request_count"] + 1

        comparison_config = {key: value for key, value in config.items() if key != "policy"}
        status1, _, body1 = request(base, "/api/benchmarks/compare", method="POST", payload=comparison_config)
        status2, _, body2 = request(base, "/api/benchmarks/compare", method="POST", payload=comparison_config)
        assert status1 == status2 == 200
        first, second = json.loads(body1), json.loads(body2)
        assert first["same_trace_for_both_policies"] is True
        assert first["trace_fingerprint"] == second["trace_fingerprint"]
        for policy in ("lru", "adaptive"):
            assert first["policies"][policy]["final_cache_keys_mru_to_lru"] == second["policies"][policy]["final_cache_keys_mru_to_lru"]
            assert first["policies"][policy]["metrics"]["hits"] == second["policies"][policy]["metrics"]["hits"]

        bad_status, _, _ = request(base, "/api/simulations", method="POST", payload={**config, "capacity_bytes": 0})
        assert bad_status == 422
        print("PASS: live HTTP health, create, step, state refresh, run, JSON/CSV export, paired comparison reproducibility, and 422 validation")
        print(f"PASS: {config['request_count']} engine requests; trace fingerprint {first['trace_fingerprint']}")
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
