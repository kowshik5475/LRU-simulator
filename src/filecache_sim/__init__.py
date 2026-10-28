"""LRU-based file cache simulator."""

from .cache import CacheStats, LRUFileCache
from .disk import SimulatedDisk
from .metrics import SimulationMetrics
from .policies import AdaptiveLRUPolicy, CachePolicy, StandardLRUPolicy
from .schemas import CacheRequest, RequestOutcome, SimulationResult
from .simulation import SimulationEngine, compare_policies
from .workloads import Workload, generate_workload, generate_workloads

__all__ = [
    "AdaptiveLRUPolicy", "CachePolicy", "CacheRequest", "CacheStats",
    "LRUFileCache", "RequestOutcome", "SimulationEngine", "SimulationMetrics",
    "SimulationResult", "SimulatedDisk", "StandardLRUPolicy", "Workload",
    "compare_policies", "generate_workload", "generate_workloads",
]
__version__ = "0.1.0"
