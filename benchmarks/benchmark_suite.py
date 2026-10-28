"""Reproducible LRU vs Adaptive LRU benchmark suite.

Examples:
    PYTHONPATH=src python benchmarks/benchmark_suite.py --smoke
    PYTHONPATH=src python benchmarks/benchmark_suite.py --seeds 5 --requests 500
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Support direct execution from a source checkout without package installation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from filecache_sim import compare_policies, generate_workload  # noqa: E402

WORKLOADS = (
    "sequential_scan",
    "hot_set",
    "uniform_random",
    "skewed_popularity",
    "changing_hot_set",
    "mixed_sizes_io",
)
SWEEP_WORKLOADS = ("hot_set", "mixed_sizes_io")
METRIC_FIELDS = (
    "requests", "read_requests", "write_requests", "hits", "misses",
    "write_hits", "write_misses", "hit_ratio", "read_hit_ratio", "admissions", "promotions",
    "scan_related_decisions", "bypasses", "evictions", "write_backs",
    "disk_reads", "disk_writes", "bytes_occupied", "capacity_bytes",
    "capacity_utilization", "average_bytes_occupied", "average_capacity_utilization",
    "actual_execution_seconds",
    "simulated_storage_seconds", "simulated_cost",
)


def _run_configuration(
    *, workload_name: str, seed: int, requests: int, files: int,
    hot_set_size: int, capacity: int,
) -> list[dict[str, Any]]:
    workload = generate_workload(
        workload_name, request_count=requests, seed=seed,
        file_count=files, hot_set_size=hot_set_size,
    )
    # compare_policies clones initial disk state and consumes the same immutable trace.
    paired = compare_policies(
        capacity, workload.requests, initial_files=workload.initial_files, seed=seed,
    )
    rows: list[dict[str, Any]] = []
    for policy_name in ("lru", "adaptive"):
        result = paired[policy_name]
        metrics = result.metrics
        rows.append({
            "scenario": workload_name,
            "scenario_group": "workload",
            "seed": seed,
            "request_count_configured": requests,
            "file_count": files,
            "hot_set_size": hot_set_size,
            "capacity_bytes": capacity,
            "policy": policy_name,
            "trace_fingerprint": _trace_fingerprint(workload.requests),
            **{key: metrics[key] for key in METRIC_FIELDS if key in metrics},
            "average_bytes_occupied": (
                sum(outcome.cache_used_bytes for outcome in result.outcomes) / len(result.outcomes)
                if result.outcomes else 0.0
            ),
            "average_capacity_utilization": (
                sum(outcome.cache_used_bytes / capacity for outcome in result.outcomes) / len(result.outcomes)
                if result.outcomes and capacity else 0.0
            ),
        })
    return rows


def _trace_fingerprint(requests: tuple[Any, ...]) -> str:
    """Stable digest proving that paired policies were given the same trace."""
    import hashlib
    payload = [
        (r.operation, r.name, r.content)
        for r in requests
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def run_benchmarks(
    *, seeds: tuple[int, ...] = (2026, 2027, 2028, 2029, 2030),
    request_count: int = 500, file_count: int = 100, hot_set_size: int = 5,
    base_capacity: int = 256, capacities: tuple[int, ...] = (64, 128, 256, 512),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Execute paired scenarios and return raw rows plus reproducibility metadata."""
    if not seeds:
        raise ValueError("at least one seed is required")
    if request_count < 0 or file_count < 1 or hot_set_size < 1:
        raise ValueError("invalid workload dimensions")
    if base_capacity < 1 or not capacities or any(c < 1 for c in capacities):
        raise ValueError("capacities must be positive")
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        for kind in WORKLOADS:
            rows.extend(_run_configuration(
                workload_name=kind, seed=seed, requests=request_count,
                files=file_count, hot_set_size=hot_set_size, capacity=base_capacity,
            ))
        # Explicit capacity sweeps on two different workload profiles.
        for kind in SWEEP_WORKLOADS:
            workload = generate_workload(
                kind, request_count=request_count, seed=seed,
                file_count=file_count, hot_set_size=hot_set_size,
            )
            fingerprint = _trace_fingerprint(workload.requests)
            for capacity in capacities:
                paired = compare_policies(
                    capacity, workload.requests,
                    initial_files=workload.initial_files, seed=seed,
                )
                for policy_name in ("lru", "adaptive"):
                    metrics = paired[policy_name].metrics
                    rows.append({
                        "scenario": kind,
                        "scenario_group": "capacity_sweep",
                        "seed": seed,
                        "request_count_configured": request_count,
                        "file_count": file_count,
                        "hot_set_size": hot_set_size,
                        "capacity_bytes": capacity,
                        "policy": policy_name,
                        "trace_fingerprint": fingerprint,
                        **{key: metrics[key] for key in METRIC_FIELDS if key in metrics},
                        "average_bytes_occupied": (
                            sum(outcome.cache_used_bytes for outcome in paired[policy_name].outcomes)
                            / len(paired[policy_name].outcomes)
                            if paired[policy_name].outcomes else 0.0
                        ),
                        "average_capacity_utilization": (
                            sum(outcome.cache_used_bytes / capacity for outcome in paired[policy_name].outcomes)
                            / len(paired[policy_name].outcomes)
                            if paired[policy_name].outcomes and capacity else 0.0
                        ),
                    })
    metadata = {
        "suite": "custom-lru-adaptive-benchmark",
        "python_version": sys.version,
        "platform": platform.platform(),
        "seeds": list(seeds),
        "request_count": request_count,
        "file_count": file_count,
        "hot_set_size": hot_set_size,
        "base_capacity_bytes": base_capacity,
        "capacity_sweep_bytes": list(capacities),
        "workloads": list(WORKLOADS),
        "capacity_sweep_workloads": list(SWEEP_WORKLOADS),
        "policies": ["lru", "adaptive"],
        "simulated_io_parameters": {
            "read_latency_seconds": 0.005, "write_latency_seconds": 0.010,
            "read_cost": 1.0, "write_cost": 2.0,
        },
        "timing_note": (
            "actual_execution_seconds measures Python wall-clock policy+engine execution; "
            "simulated_storage_seconds is modeled from disk operation counts and configured "
            "latencies. Neither is physical storage benchmark data."
        ),
        "rows": len(rows),
    }
    return rows, metadata


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate across independent seeds; report sample standard deviation when possible."""
    keys = sorted({
        (row["scenario_group"], row["scenario"], row["capacity_bytes"], row["policy"])
        for row in rows
    })
    summary: list[dict[str, Any]] = []
    numeric = (
        "hit_ratio", "evictions", "write_backs", "disk_reads", "disk_writes",
        "bytes_occupied", "capacity_utilization", "average_bytes_occupied",
        "average_capacity_utilization", "actual_execution_seconds",
        "simulated_storage_seconds", "simulated_cost",
    )
    for group, scenario, capacity, policy in keys:
        selected = [
            row for row in rows
            if (row["scenario_group"], row["scenario"], row["capacity_bytes"], row["policy"])
            == (group, scenario, capacity, policy)
        ]
        record: dict[str, Any] = {
            "scenario_group": group, "scenario": scenario,
            "capacity_bytes": capacity, "policy": policy,
            "independent_runs": len(selected),
        }
        for field in numeric:
            values = [float(row[field]) for row in selected]
            record[f"{field}_mean"] = statistics.fmean(values)
            record[f"{field}_stdev"] = statistics.stdev(values) if len(values) > 1 else 0.0
        summary.append(record)
    return summary


def chart_payload(summary: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce frontend-friendly series, one row per scenario/capacity/policy."""
    return {
        "schema_version": 1,
        "description": "Seed aggregates; actual runtime and modeled I/O time are separate.",
        "series": summary,
        "charts": {
            "hit_ratio": {
                "metric": "hit_ratio_mean", "variability": "hit_ratio_stdev",
                "label": "Mean cache hit ratio",
            },
            "evictions": {
                "metric": "evictions_mean", "variability": "evictions_stdev",
                "label": "Mean eviction count",
            },
            "write_backs": {
                "metric": "write_backs_mean", "variability": "write_backs_stdev",
                "label": "Mean write-back count",
            },
            "execution_time": {
                "metric": "actual_execution_seconds_mean",
                "variability": "actual_execution_seconds_stdev",
                "label": "Measured Python execution time (seconds)",
            },
            "simulated_storage_time": {
                "metric": "simulated_storage_seconds_mean",
                "variability": "simulated_storage_seconds_stdev",
                "label": "Modeled storage latency (seconds; not physical timing)",
            },
        },
    }


def export_results(
    rows: list[dict[str, Any]], metadata: dict[str, Any], output_dir: str | Path,
) -> dict[str, str]:
    """Export raw records and aggregated chart-ready data in CSV and JSON."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    chart = chart_payload(summary)
    raw_csv = destination / "raw_results.csv"
    raw_json = destination / "raw_results.json"
    summary_csv = destination / "summary.csv"
    summary_json = destination / "summary.json"
    chart_json = destination / "chart_data.json"
    manifest_json = destination / "manifest.json"

    if rows:
        with raw_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        raw_csv.write_text("", encoding="utf-8")
    with raw_json.open("w", encoding="utf-8") as handle:
        json.dump({"metadata": metadata, "results": rows}, handle, indent=2)
    if summary:
        with summary_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)
    else:
        summary_csv.write_text("", encoding="utf-8")
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    chart_json.write_text(json.dumps(chart, indent=2), encoding="utf-8")
    manifest_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {name: str(path) for name, path in {
        "raw_csv": raw_csv, "raw_json": raw_json,
        "summary_csv": summary_csv, "summary_json": summary_json,
        "chart_json": chart_json, "manifest": manifest_json,
    }.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="small one-seed validation run")
    parser.add_argument("--seed", type=int, default=2026, help="base seed")
    parser.add_argument("--seeds", type=int, default=5, help="number of independent seeds")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--capacity", type=int, default=256)
    parser.add_argument("--capacities", type=int, nargs="+", default=[64, 128, 256, 512])
    parser.add_argument("--output-dir", default="benchmark-results")
    args = parser.parse_args()
    if args.smoke:
        seeds, requests, files, capacities = (args.seed,), 30, 20, (32, 64)
        output_dir = str(Path(args.output_dir) / "smoke")
    else:
        if args.seeds < 1:
            parser.error("--seeds must be >= 1")
        seeds = tuple(args.seed + i for i in range(args.seeds))
        requests, files, capacities = args.requests, args.files, tuple(args.capacities)
        output_dir = args.output_dir

    started = time.perf_counter()
    rows, metadata = run_benchmarks(
        seeds=seeds, request_count=requests, file_count=files,
        base_capacity=args.capacity, capacities=capacities,
    )
    metadata["benchmark_wall_clock_seconds"] = time.perf_counter() - started
    paths = export_results(rows, metadata, output_dir)
    print(f"Completed {len(rows)} paired-policy result rows in "
          f"{metadata['benchmark_wall_clock_seconds']:.3f}s")
    print(f"Seeds: {seeds}; requests/trace: {requests}; files: {files}")
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
