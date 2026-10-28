# Benchmark Methodology and Recorded Findings

## Reproduce the checked-in full run

From the repository root with the package dependencies installed:

```bash
PYTHONPATH=src python benchmarks/benchmark_suite.py \
  --seed 2026 --seeds 5 --requests 500 --files 100 \
  --capacity 256 --capacities 64 128 256 512 \
  --output-dir benchmark-results/reproduced-full
```

The exact options are also recorded in `benchmark-results/full/manifest.json`. To run a quick check:

```bash
PYTHONPATH=src python benchmarks/benchmark_suite.py --smoke --output-dir benchmark-results/reproduced-smoke
```

Do not overwrite `benchmark-results/full/` if you want to preserve the checked-in run. Outputs include per-scenario raw CSV/JSON, mean and sample standard deviation summaries, chart data, and a manifest.

## Environment and configuration

The checked-in `full` manifest records:

- Python: **3.13.5**
- Platform: **Linux-6.18.55-x86_64-with-glibc2.41**
- Seeds: **2026, 2027, 2028, 2029, 2030**
- Requests: **500 per workload and seed**
- File count: **100**; hot-set size: **5**
- Base capacity: **256 bytes**
- Capacity sweep: **64, 128, 256, 512 bytes**, for `hot_set` and `mixed_sizes_io`
- Workloads at base capacity: `sequential_scan`, `hot_set`, `uniform_random`, `skewed_popularity`, `changing_hot_set`, `mixed_sizes_io`
- Policies: `lru`, `adaptive`
- Paired comparisons: both policies use the same trace and initial simulated-disk contents for each scenario/seed/capacity.
- Modeled I/O assumptions: read latency 0.005 s, write latency 0.010 s, read cost 1.0, write cost 2.0.

The manifest contains 140 summary rows and reports a total suite wall-clock duration of about 1.00 second for this recorded environment. This is a benchmark harness duration, not application throughput; wall-clock values vary between runs.

## Results: base capacity 256 bytes

Values below are means across the five recorded seeds. Hit ratio is the **read hit ratio** (read hits divided by read hits plus read misses), excluding write requests; write hits and write misses are recorded separately in raw results. Cost is the simulator's arbitrary modeled cost units (one per logical disk read, two per logical disk write). Write-backs are mean counts.

| Workload | LRU read hit ratio | Adaptive read hit ratio | LRU modeled cost | Adaptive modeled cost | LRU write-backs | Adaptive write-backs |
|---|---:|---:|---:|---:|---:|---:|
| Sequential scan | 0.00% | 0.00% | 500.0 | 500.0 | 0.0 | 0.0 |
| Hot set | 99.00% | 99.00% | 5.0 | 5.0 | 0.0 | 0.0 |
| Uniform random | 15.44% | 15.36% | 422.8 | 423.2 | 0.0 | 0.0 |
| Skewed popularity | 49.96% | 53.68% | 250.2 | 231.6 | 0.0 | 0.0 |
| Changing hot set | 96.00% | 95.92% | 20.0 | 20.4 | 0.0 | 0.0 |
| Mixed sizes / I/O | 10.39% | 10.45% | 580.2 | 578.8 | 142.4 | 141.8 |

**Interpretation:** in this recorded configuration, adaptive LRU had a higher mean hit ratio on the skewed-popularity workload (53.68% vs 49.96%) and lower modeled cost (231.6 vs 250.2). It was effectively tied on the hot set, marginally lower on uniform random and changing hot set, and both policies had zero hits on the sequential scan. Mixed I/O was close in hit ratio and modeled cost, with slightly fewer mean write-backs for adaptive. This is a workload-specific observation, not proof of general superiority.

## Capacity sweep illustration

For the `hot_set` sweep at **64 bytes**, LRU recorded a mean 66.60% hit ratio and adaptive 61.88%; at **128 bytes**, both policies recorded 99.00% hit ratio. This is a useful counterexample to any claim that adaptive always wins. Inspect `summary.csv` for the full capacity-sweep metrics rather than extrapolating from one example.

## How to interpret timing

- `actual_execution_seconds` is measured Python wall-clock time for the simulator and its instrumentation. It is sensitive to interpreter, machine load, and timer noise; tiny runs should not be treated as robust performance measurements.
- `simulated_storage_seconds` is calculated from logical disk operation counts and the configured latencies. No sleep or physical I/O is performed.
- `simulated_cost` uses configurable arbitrary units, not currency or real cloud billing.
- Hit ratio and operation counts are deterministic for a fixed implementation/configuration/seed; wall-clock durations are not expected to be bit-for-bit reproducible.
- The five seeds are a small experimental sample. Sample standard deviations are included in the CSV/JSON summary; this is not a formal statistical study.

## Limitations

This benchmark is synthetic and in-process. It does not represent real file-system traces, OS page-cache effects, SSD/HDD behavior, filesystem metadata, concurrent workloads, or persistence durability. Workload generators and selected capacities strongly affect results. The adaptive strategy is inspired by established segmented-LRU/2Q-style concepts; this experiment does not establish algorithmic novelty.
