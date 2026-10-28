from filecache_sim import CacheRequest, SimulationEngine, compare_policies, generate_workload


def test_step_executes_exactly_one_request_and_preserves_order():
    requests = (CacheRequest("read", "a"), CacheRequest("read", "b"), CacheRequest("read", "a"))
    engine = SimulationEngine(16, requests, initial_files={"a": "a", "b": "b"})
    first = engine.step()
    assert first.index == 0 and first.request.name == "a" and first.miss is True
    assert len(engine.outcomes) == 1
    second = engine.step()
    assert second.index == 1 and second.request.name == "b"
    third = engine.step()
    assert third.index == 2 and third.request.name == "a" and third.hit is True
    assert engine.step() is None


def test_metrics_hit_ratio_disk_io_and_capacity_utilization():
    requests = [CacheRequest("read", "a"), CacheRequest("read", "a"), CacheRequest("read", "missing")]
    result = SimulationEngine(4, requests, initial_files={"a": "abcd"}).run()
    assert result.metrics["requests"] == 3
    assert result.metrics["hits"] == 1
    assert result.metrics["misses"] == 2
    assert result.metrics["hit_ratio"] == 1 / 3
    assert result.metrics["disk_reads"] == 2
    assert result.metrics["bytes_occupied"] == 4
    assert result.metrics["capacity_utilization"] == 1.0


def test_read_hit_ratio_excludes_write_hits_and_tracks_write_outcomes_separately():
    requests = [
        CacheRequest("read", "a"),
        CacheRequest("read", "a"),
        CacheRequest("write", "a", "new"),
        CacheRequest("write", "b", "value"),
        CacheRequest("read", "missing"),
    ]
    result = SimulationEngine(16, requests, initial_files={"a": "old"}).run()
    metrics = result.metrics
    assert metrics["requests"] == 5
    assert metrics["read_requests"] == 3
    assert metrics["write_requests"] == 2
    assert metrics["hits"] == 1
    assert metrics["misses"] == 2
    assert metrics["hit_ratio"] == metrics["read_hit_ratio"] == 1 / 3
    assert metrics["write_hits"] == 1
    assert metrics["write_misses"] == 1


def test_seeded_workload_generation_is_repeatable_and_label_is_not_in_requests():
    first = generate_workload("uniform_random", request_count=50, seed=42, file_count=9)
    second = generate_workload("uniform_random", request_count=50, seed=42, file_count=9)
    assert first == second
    assert len(first.requests) == 50
    assert all(not hasattr(request, "workload") for request in first.requests)


def test_all_workload_kinds_generate_valid_requests():
    kinds = ["sequential_scan", "hot_set", "uniform_random", "skewed_popularity", "changing_hot_set", "mixed_sizes_io"]
    for kind in kinds:
        workload = generate_workload(kind, request_count=100, seed=7, file_count=20)
        result = SimulationEngine(64, workload.requests, initial_files=workload.initial_files, seed=workload.seed).run()
        assert result.metrics["requests"] == 100
        assert result.metrics["bytes_occupied"] <= 64
        assert result.metrics["bytes_occupied"] >= 0


def test_compare_policies_receives_same_trace_and_capacity():
    workload = generate_workload("mixed_sizes_io", request_count=80, seed=123, file_count=12)
    results = compare_policies(32, workload.requests, initial_files=workload.initial_files, seed=123)
    assert set(results) == {"lru", "adaptive"}
    assert len(results["lru"].outcomes) == len(results["adaptive"].outcomes) == 80
    assert [x.request for x in results["lru"].outcomes] == [x.request for x in results["adaptive"].outcomes]
    assert all(r.metrics["bytes_occupied"] <= 32 for r in results.values())


def test_oversized_write_bypasses_cache_and_cost_is_separate_from_wall_time():
    request = CacheRequest("write", "large", "x" * 20)
    result = SimulationEngine(4, [request], read_latency_seconds=2, write_latency_seconds=3,
                              read_cost=5, write_cost=7).run()
    outcome = result.outcomes[0]
    assert outcome.bypassed
    assert not outcome.admitted
    assert outcome.disk_writes_delta == 1
    assert outcome.simulated_storage_seconds == 3
    assert outcome.simulated_cost == 7
    assert outcome.elapsed_seconds >= 0
    assert result.metrics["actual_execution_seconds"] >= 0


def test_dirty_eviction_records_write_back_and_preserves_disk_content():
    requests = [CacheRequest("write", "a", "aaaa"), CacheRequest("write", "b", "bbbb")]
    result = SimulationEngine(4, requests).run()
    assert result.outcomes[1].evicted == ("a",)
    assert result.outcomes[1].write_backs == ("a",)
    assert result.metrics["write_backs"] == 1


def test_flush_and_delete_requests_are_recorded_in_order():
    requests = [CacheRequest("write", "a", "v"), CacheRequest("flush"), CacheRequest("delete", "a")]
    engine = SimulationEngine(4, requests)
    result = engine.run()
    assert [o.request.operation for o in result.outcomes] == ["write", "flush", "delete"]
    assert result.outcomes[1].write_backs == ("a",)
    assert result.outcomes[2].cache_used_bytes == 0


def test_simulated_latency_and_cost_are_zero_when_configured_zero():
    result = SimulationEngine(8, [CacheRequest("read", "a")], initial_files={"a": "a"},
                              read_latency_seconds=0, write_latency_seconds=0,
                              read_cost=0, write_cost=0).run()
    assert result.metrics["simulated_storage_seconds"] == 0
    assert result.metrics["simulated_cost"] == 0
