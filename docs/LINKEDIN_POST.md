I built a Custom LRU-Based Adaptive File Cache Simulator as an end-to-end systems project.

It combines a Python cache engine and CLI, a FastAPI backend, and a React + TypeScript dashboard. It compares standard Least Recently Used (LRU) with a configurable probationary/protected policy inspired by segmented-LRU and 2Q-style ideas. The simulator includes byte-based capacity accounting, write-back behavior, seeded synthetic workloads, per-request metrics, charts, and JSON/CSV export.

In the checked-in five-seed experiment (500 requests per workload, 256-byte base capacity), the adaptive policy's mean hit ratio on the skewed-popularity workload was 53.68%, compared with 49.96% for standard LRU. Results were not uniformly better: on uniform random access, LRU was slightly higher (15.44% vs 15.36%), and on a repeated hot-set workload both were 99.00%. These are synthetic, configuration-specific observations—not a claim that adaptive caching is universally superior.

Important scope note: backing storage is simulated in memory; this project does not intercept or benchmark physical disk I/O. The repository includes reproducible benchmark artifacts, API/integration tests, architecture and algorithm documentation, and a live HTTP smoke script.

Project focus: algorithms, API design, reproducible experiments, and full-stack integration.

#Python #SystemsProgramming #FastAPI #React #Algorithms #SoftwareEngineering
