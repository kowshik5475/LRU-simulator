"""Small reproducible simulation example; run with PYTHONPATH=src python simulation_example.py."""
from filecache_sim import SimulationEngine, compare_policies, generate_workload

workload = generate_workload("hot_set", request_count=100, seed=2026, file_count=30)
results = compare_policies(128, workload.requests, initial_files=workload.initial_files, seed=workload.seed)
for name, result in results.items():
    print(name, result.metrics)

engine = SimulationEngine(128, workload.requests, policy="adaptive",
                          initial_files=workload.initial_files, seed=workload.seed)
first = engine.step()
print("first outcome:", first)
print("complete metrics:", engine.run().metrics)
