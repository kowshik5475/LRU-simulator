"""Cache replacement/admission policy strategies.

The default policy delegates victim selection to the engine's global LRU list.
The adaptive policy uses a probationary/protected, history-based admission
strategy inspired by segmented LRU and 2Q-style caching. It does not inspect
future requests or workload labels.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class CachePolicy(Protocol):
    """Strategy interface consumed by the cache engine.

    ``lru_name`` is the engine's current least-recently-used filename. A policy
    may choose it or another resident entry. Policy hooks must not mutate cache
    content or byte accounting.
    """

    name: str

    def on_admit(self, name: str, size_bytes: int) -> None: ...
    def on_access(self, name: str, size_bytes: int) -> None: ...
    def on_remove(self, name: str, size_bytes: int) -> None: ...
    def select_victim(self, lru_name: Optional[str]) -> Optional[str]: ...
    def on_evict(self, name: str) -> None: ...
    def diagnostics(self) -> Dict[str, int | float | str]: ...


class StandardLRUPolicy:
    """Reference policy: evict the globally least-recently-used entry."""

    name = "lru"

    def on_admit(self, name: str, size_bytes: int) -> None:
        pass

    def on_access(self, name: str, size_bytes: int) -> None:
        pass

    def on_remove(self, name: str, size_bytes: int) -> None:
        pass

    def select_victim(self, lru_name: Optional[str]) -> Optional[str]:
        return lru_name

    def on_evict(self, name: str) -> None:
        pass

    def diagnostics(self) -> Dict[str, int | float | str]:
        return {"policy": self.name}


class AdaptiveLRUPolicy:
    """Scan-resistant segmented policy using only observed access history.

    Every admitted item starts in probationary. Its admission counts as its
    first observed use; it is promoted after ``promotion_threshold`` total
    observed uses. Protected entries are kept in their own LRU order.

    Eviction prefers the oldest probationary entry while any probationary
    entries exist; only when probationary is empty does it evict protected
    LRU. Thus one-time scans preferentially displace probationary candidates
    rather than repeatedly used protected entries.

    ``protected_fraction`` sets a soft byte target for protected entries.
    When protected usage exceeds the target, least-recently-used protected
    entries are demoted to probationary until usage is at/below target, except
    that a single protected item larger than the target is retained. A bounded
    ghost history remembers evicted probationary *names* (never file content).
    Re-admissions of ghosted names are evidence that the previous admission
    decision may have been too scan-resistant; every ``ghost_hit_threshold``
    such events demotes one protected LRU entry, making room for a changing hot
    set to prove reuse. The cache engine's total byte capacity remains the
    hard limit.
    """

    name = "adaptive_lru"

    def __init__(
        self,
        capacity_bytes: int,
        *,
        protected_fraction: float = 0.8,
        promotion_threshold: int = 2,
        ghost_hit_threshold: int = 2,
        ghost_history_limit: int = 256,
    ) -> None:
        if isinstance(capacity_bytes, bool) or not isinstance(capacity_bytes, int):
            raise TypeError("capacity_bytes must be an integer")
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        if not 0.0 < protected_fraction < 1.0:
            raise ValueError("protected_fraction must be between 0 and 1")
        if isinstance(promotion_threshold, bool) or not isinstance(promotion_threshold, int):
            raise TypeError("promotion_threshold must be an integer")
        if promotion_threshold < 2:
            raise ValueError("promotion_threshold must be at least 2")
        if isinstance(ghost_hit_threshold, bool) or not isinstance(ghost_hit_threshold, int):
            raise TypeError("ghost_hit_threshold must be an integer")
        if ghost_hit_threshold < 1:
            raise ValueError("ghost_hit_threshold must be positive")
        if isinstance(ghost_history_limit, bool) or not isinstance(ghost_history_limit, int):
            raise TypeError("ghost_history_limit must be an integer")
        if ghost_history_limit < 1:
            raise ValueError("ghost_history_limit must be positive")

        self.capacity_bytes = capacity_bytes
        self.protected_fraction = protected_fraction
        self.promotion_threshold = promotion_threshold
        self.ghost_hit_threshold = ghost_hit_threshold
        self.ghost_history_limit = ghost_history_limit
        # OrderedDict order is LRU -> MRU in each segment.
        self._probationary: OrderedDict[str, list[int]] = OrderedDict()
        self._protected: OrderedDict[str, int] = OrderedDict()
        self._probationary_bytes = 0
        self._protected_bytes = 0
        self._ghost: OrderedDict[str, None] = OrderedDict()
        self._ghost_hits_since_adjustment = 0
        self.promotions = 0
        self.scan_related_decisions = 0
        self.admissions = 0
        self.evictions = 0
        self.ghost_hits = 0
        self.adaptive_demotions = 0

    def on_admit(self, name: str, size_bytes: int) -> None:
        """Admit a new resident into probationary with one observed use."""
        if name in self._ghost:
            del self._ghost[name]
            self.ghost_hits += 1
            self._ghost_hits_since_adjustment += 1
            if self._ghost_hits_since_adjustment >= self.ghost_hit_threshold:
                self._demote_protected_lru()
                self._ghost_hits_since_adjustment = 0
        self._probationary[name] = [size_bytes, 1]
        self._probationary_bytes += size_bytes
        self.admissions += 1

    def on_access(self, name: str, size_bytes: int) -> None:
        """Update observed recency and promote repeatedly used probationary items."""
        if name in self._protected:
            self._protected.move_to_end(name)
            return
        record = self._probationary.get(name)
        if record is None:
            return
        record[1] += 1
        self._probationary.move_to_end(name)
        if record[1] >= self.promotion_threshold:
            self._probationary.pop(name)
            self._probationary_bytes -= record[0]
            self._protected[name] = record[0]
            self._protected_bytes += record[0]
            self.promotions += 1
            self._rebalance_protected()

    def _demote_protected_lru(self) -> bool:
        """Demote one protected LRU entry, returning whether one was available."""
        if not self._protected:
            return False
        name, size = self._protected.popitem(last=False)
        self._protected_bytes -= size
        self._probationary[name] = [size, self.promotion_threshold - 1]
        self._probationary_bytes += size
        self.adaptive_demotions += 1
        return True

    def _rebalance_protected(self) -> None:
        """Demote protected LRU entries when the soft protected target is exceeded."""
        target = int(self.capacity_bytes * self.protected_fraction)
        while self._protected_bytes > target and len(self._protected) > 1:
            self._demote_protected_lru()

    def on_remove(self, name: str, size_bytes: int) -> None:
        """Forget a resident when it is replaced, deleted, or evicted."""
        record = self._probationary.pop(name, None)
        if record is not None:
            self._probationary_bytes -= record[0]
        protected_size = self._protected.pop(name, None)
        if protected_size is not None:
            self._protected_bytes -= protected_size

    def select_victim(self, lru_name: Optional[str]) -> Optional[str]:
        """Prefer probationary LRU; fall back to protected LRU."""
        if self._probationary:
            return next(iter(self._probationary))
        if self._protected:
            return next(iter(self._protected))
        return lru_name

    def on_evict(self, name: str) -> None:
        """Record eviction; retain bounded ghost history for evicted probationary names."""
        if name in self._probationary:
            if self._protected:
                self.scan_related_decisions += 1
            self._ghost[name] = None
            self._ghost.move_to_end(name)
            while len(self._ghost) > self.ghost_history_limit:
                self._ghost.popitem(last=False)
        self.evictions += 1

    def diagnostics(self) -> Dict[str, int | float | str]:
        """Return policy counters and current segment occupancy."""
        return {
            "policy": self.name,
            "promotions": self.promotions,
            "scan_related_decisions": self.scan_related_decisions,
            "admissions": self.admissions,
            "evictions": self.evictions,
            "probationary_entries": len(self._probationary),
            "protected_entries": len(self._protected),
            "probationary_bytes": self._probationary_bytes,
            "protected_bytes": self._protected_bytes,
            "protected_fraction": self.protected_fraction,
            "promotion_threshold": self.promotion_threshold,
            "ghost_hits": self.ghost_hits,
            "adaptive_demotions": self.adaptive_demotions,
            "ghost_history_entries": len(self._ghost),
            "ghost_hit_threshold": self.ghost_hit_threshold,
            "ghost_history_limit": self.ghost_history_limit,
        }
