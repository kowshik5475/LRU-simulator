"""Run reproducible generated workloads through both cache policies.

Usage: PYTHONPATH=src python benchmarks/compare_simulation.py --seed 2026
"""
from __future__ import annotations

import argparse

from filecache_sim import SimulationEngine, compare_policies, generate_workloads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--capacity", type=int, default=256)
    parser.add_argument("--files", type=int, default=100)
    args = parser.parse_args()
    workloads = generate_workloads(
        seed=args.seed, request_count=args.requests, file_count=args.files
    )
    print("workload,policy,requests,hits,misses,hit_ratio,evictions,disk_reads,disk_writes,bytes_occupied,utilization,simulated_seconds,actual_seconds")
    for workload in workloads:
        results = compare_policies(
            args.capacity, workload.requests,
            initial_files=workload.initial_files, seed=workload.seed,
        )
        for policy_name, result in results.items():
            m = result.metrics
            print(
                f"{workload.name},{policy_name},{m['requests']},{m['hits']},"
                f"{m['misses']},{m['hit_ratio']:.6f},{m['evictions']},"
                f"{m['disk_reads']},{m['disk_writes']},{m['bytes_occupied']},"
                f"{m['capacity_utilization']:.6f},{m['simulated_storage_seconds']:.6f},"
                f"{m['actual_execution_seconds']:.9f}"
            )


if __name__ == "__main__":
    main()
