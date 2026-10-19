"""LRU-based file cache simulator (mini-OS demonstration)."""

from .cache import CacheStats, LRUFileCache
from .disk import SimulatedDisk

__all__ = ["CacheStats", "LRUFileCache", "SimulatedDisk"]
__version__ = "0.1.0"
