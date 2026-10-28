from __future__ import annotations

import csv
import json

from filecache_sim import CacheRequest, SimulationEngine, compare_policies
from benchmarks.benchmark_suite import export_results, run_benchmarks, summarize


def test_benchmark_reproducible_trace_and_metrics_except_wall_clock():
    rows_a, meta_a = run_benchmarks(
        seeds=(77,), request_count=12, file_count=8, hot_set_size=3,
        base_capacity=32, capacities=(8, 16),
    )
    rows_b, meta_b = run_benchmarks(
        seeds=(77,), request_count=12, file_count=8, hot_set_size=3,
        base_capacity=32, capacities=(8, 16),
    )
    assert [(r["scenario"], r["capacity_bytes"], r["policy"], r["trace_fingerprint"])
            for r in rows_a] == [
        (r["scenario"], r["capacity_bytes"], r["policy"], r["trace_fingerprint"])
        for r in rows_b
    ]
    ignored = {"actual_execution_seconds"}
    for a, b in zip(rows_a, rows_b):
        for key in a:
            if key not in ignored:
                assert a[key] == b[key]
    assert meta_a["seeds"] == meta_b["seeds"] == [77]


def test_policy_comparison_uses_identical_trace_and_initial_state():
    requests = (
        CacheRequest("read", "a"),
        CacheRequest("read", "b"),
        CacheRequest("read", "a"),
        CacheRequest("write", "b", "changed"),
        CacheRequest("flush"),
    )
    initial = {"a": "A", "b": "B"}
    results = compare_policies(2, requests, initial_files=initial, seed=9)
    assert len(results["lru"].outcomes) == len(results["adaptive"].outcomes) == len(requests)
    assert [o.request for o in results["lru"].outcomes] == [
        o.request for o in results["adaptive"].outcomes
    ] == list(requests)
    assert results["lru"].outcomes[0].disk_reads_delta == results["adaptive"].outcomes[0].disk_reads_delta
    assert results["lru"].capacity_bytes == results["adaptive"].capacity_bytes == 2


def test_metric_aggregation_reports_mean_and_variability():
    rows = [
        {"scenario_group": "workload", "scenario": "hot_set", "capacity_bytes": 10,
         "policy": "lru", "hit_ratio": 0.5, "evictions": 2, "write_backs": 0,
         "disk_reads": 5, "disk_writes": 0, "bytes_occupied": 8,
         "capacity_utilization": 0.8, "average_bytes_occupied": 8, "average_capacity_utilization": 0.8, "actual_execution_seconds": 0.01,
         "simulated_storage_seconds": 0.02, "simulated_cost": 5},
        {"scenario_group": "workload", "scenario": "hot_set", "capacity_bytes": 10,
         "policy": "lru", "hit_ratio": 1.0, "evictions": 4, "write_backs": 2,
         "disk_reads": 0, "disk_writes": 2, "bytes_occupied": 10,
         "capacity_utilization": 1.0, "average_bytes_occupied": 9, "average_capacity_utilization": 0.9, "actual_execution_seconds": 0.03,
         "simulated_storage_seconds": 0.04, "simulated_cost": 4},
    ]
    summary = summarize(rows)
    assert len(summary) == 1
    assert summary[0]["hit_ratio_mean"] == 0.75
    assert summary[0]["hit_ratio_stdev"] > 0
    assert summary[0]["independent_runs"] == 2


def test_exported_raw_csv_json_and_chart_data(tmp_path):
    rows, metadata = run_benchmarks(
        seeds=(4,), request_count=4, file_count=3, hot_set_size=2,
        base_capacity=16, capacities=(8,),
    )
    paths = export_results(rows, metadata, tmp_path)
    with open(paths["raw_csv"], newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    raw = json.loads(open(paths["raw_json"], encoding="utf-8").read())
    chart = json.loads(open(paths["chart_json"], encoding="utf-8").read())
    assert len(csv_rows) == len(rows)
    assert raw["metadata"]["rows"] == len(rows)
    assert chart["schema_version"] == 1
    assert "hit_ratio" in chart["charts"]
