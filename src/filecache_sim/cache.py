"""Standard LRU file-cache simulator with write-back persistence.

The cache uses a dictionary for O(1) average filename lookup and a doubly
linked list for O(1) recency updates and LRU eviction. Capacity is measured in
UTF-8 encoded bytes, not Python Unicode code points.

Writes update the cache and mark entries dirty. Dirty content is persisted to
the simulated disk on eviction or :meth:`LRUFileCache.flush`. A file whose
encoded content exceeds capacity bypasses the cache. Capacity must be positive;
zero and negative capacities raise :class:`ValueError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .disk import SimulatedDisk
from .policies import CachePolicy, StandardLRUPolicy

EventHandler = Callable[[str], None]


def _content_size_bytes(content: str) -> int:
    """Return the size of *content* encoded as UTF-8 bytes.

    Unicode strings that cannot be encoded as valid UTF-8 raise
    ``UnicodeEncodeError`` rather than receiving misleading size accounting.
    """
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    return len(content.encode("utf-8"))


@dataclass
class CacheStats:
    """Counters describing cache behavior."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    write_backs: int = 0

    @property
    def hit_ratio(self) -> float:
        """Return the read hit ratio, or zero before any reads."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class _Node:
    """Internal doubly linked list node."""

    __slots__ = ("name", "content", "dirty", "prev", "next")

    def __init__(self, name: str, content: str, dirty: bool = False) -> None:
        self.name = name
        self.content = content
        self.dirty = dirty
        self.prev: Optional[_Node] = None
        self.next: Optional[_Node] = None

    @property
    def size(self) -> int:
        """Content size in UTF-8 encoded bytes."""
        return _content_size_bytes(self.content)


class LRUFileCache:
    """A byte-capacity LRU cache backed by :class:`SimulatedDisk`.

    Public operations retain the original API. Event-handler exceptions are
    intentionally suppressed: logging/observation must not interrupt a cache
    mutation halfway through and leave the data structures inconsistent.
    """

    def __init__(
        self,
        capacity_bytes: int,
        disk: SimulatedDisk,
        on_event: Optional[EventHandler] = None,
        policy: Optional[CachePolicy] = None,
    ) -> None:
        if isinstance(capacity_bytes, bool) or not isinstance(capacity_bytes, int):
            raise TypeError("capacity_bytes must be an integer")
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self.capacity_bytes = capacity_bytes
        self.used_bytes = 0
        self.disk = disk
        self.stats = CacheStats()
        self._event_handler = on_event
        self.policy: CachePolicy = policy if policy is not None else StandardLRUPolicy()
        policy_capacity = getattr(self.policy, "capacity_bytes", capacity_bytes)
        if policy_capacity != capacity_bytes:
            raise ValueError("policy capacity_bytes must match cache capacity_bytes")

        self._map: dict[str, _Node] = {}
        self._head = _Node("HEAD", "")  # MRU sentinel
        self._tail = _Node("TAIL", "")  # LRU sentinel
        self._head.next = self._tail
        self._tail.prev = self._head

    # ------------------------------------------------------ list helpers
    def _emit(self, message: str) -> None:
        """Emit a best-effort event without allowing observers to break cache operations."""
        if self._event_handler is not None:
            try:
                self._event_handler(message)
            except Exception:
                # Observability callbacks must not compromise cache consistency.
                pass

    def _unlink(self, node: _Node) -> None:
        """Remove a linked node from the recency list."""
        if node.prev is None or node.next is None:
            raise RuntimeError("cannot unlink a node that is not linked")
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = None
        node.next = None

    def _push_front(self, node: _Node) -> None:
        """Insert a node as the most-recently-used entry."""
        first = self._head.next
        if first is None:
            raise RuntimeError("LRU list is corrupt")
        node.next = first
        node.prev = self._head
        first.prev = node
        self._head.next = node

    def _touch(self, node: _Node) -> None:
        """Mark a linked node as most recently used."""
        if node.prev is not None:
            self._unlink(node)
        self._push_front(node)

    def _remove(self, name: str) -> Optional[_Node]:
        """Remove an entry and update byte accounting; do not persist it."""
        node = self._map.pop(name, None)
        if node is not None:
            self._unlink(node)
            self.used_bytes -= node.size
            self.policy.on_remove(name, node.size)
        return node

    # ----------------------------------------------------------- internals
    def _evict_until_fits(self, needed_bytes: int) -> None:
        """Evict LRU entries until *needed_bytes* fit in the cache."""
        while self.used_bytes + needed_bytes > self.capacity_bytes:
            lru_node = self._tail.prev
            if lru_node is None or lru_node is self._head:
                raise RuntimeError("unable to free enough cache capacity")
            victim_name = self.policy.select_victim(lru_node.name)
            if victim_name is None or victim_name not in self._map:
                raise RuntimeError("cache policy selected an invalid eviction victim")
            victim = self._map[victim_name]
            self.policy.on_evict(victim.name)
            self._remove(victim.name)
            self.stats.evictions += 1
            note = ""
            if victim.dirty:
                self.disk.write(victim.name, victim.content)
                self.stats.write_backs += 1
                note = " (dirty -> written back to disk)"
            self._emit(f"[EVICT] {victim.name} ({victim.size}B){note}")

    def _insert(self, name: str, content: str, dirty: bool) -> None:
        """Insert content unless it exceeds capacity; oversized content bypasses cache."""
        size_bytes = _content_size_bytes(content)
        if size_bytes > self.capacity_bytes:
            if dirty:
                self._emit(f"[BYPASS] {name} larger than cache; writing directly to disk")
                self.disk.write(name, content)
            else:
                self._emit(f"[BYPASS] {name} larger than cache; not retained in cache")
            return

        self._evict_until_fits(size_bytes)
        node = _Node(name, content, dirty)
        self._push_front(node)
        self._map[name] = node
        self.used_bytes += size_bytes
        self.policy.on_admit(name, size_bytes)

    # -------------------------------------------------------- public API
    def read(self, name: str) -> Optional[str]:
        """Return content from cache/disk, or ``None`` if the file is absent.

        A cache miss increments the miss counter and the simulated disk's read
        counter. Oversized disk content is returned but is not cached.
        """
        node = self._map.get(name)
        if node is not None:
            self.stats.hits += 1
            self._touch(node)
            self.policy.on_access(name, node.size)
            self._emit(f"[HIT]  {name}")
            return node.content

        self.stats.misses += 1
        self._emit(f"[MISS] {name} -> reading from disk")
        content = self.disk.read(name)
        if content is None:
            self._emit(f"[ERR]  file not found: {name}")
            return None
        self._insert(name, content, dirty=False)
        return content

    def write(self, name: str, content: str) -> None:
        """Update content using write-back; oversized content goes directly to disk.

        The disk's metadata entry is created immediately for compatibility with
        the original simulator. Content is persisted immediately only when it
        bypasses the cache, or later on dirty eviction/flush.
        """
        size_bytes = _content_size_bytes(content)
        self._remove(name)
        self._emit(f"[WRITE] {name} ({size_bytes}B) cached as dirty")
        self.disk.create(name)
        self._insert(name, content, dirty=True)

    def delete(self, name: str) -> None:
        """Delete a cached entry and its simulated-disk file, if present."""
        self._remove(name)
        self.disk.delete(name)
        self._emit(f"[DELETE] {name}")

    def flush(self) -> None:
        """Persist every dirty entry and mark it clean.

        Repeated flushes do not write clean entries again.
        """
        node = self._head.next
        while node is not self._tail:
            if node is None:
                raise RuntimeError("LRU list is corrupt")
            if node.dirty:
                self.disk.write(node.name, node.content)
                node.dirty = False
                self.stats.write_backs += 1
                self._emit(f"[FLUSH] {node.name}")
            node = node.next

    # ------------------------------------------------------ introspection
    def entries(self) -> List[_Node]:
        """Return cache nodes ordered from MRU to LRU.

        The node type is retained for compatibility with the existing CLI and
        callers that inspect ``name``, ``content``, ``dirty`` or ``size``.
        """
        out: List[_Node] = []
        node = self._head.next
        while node is not self._tail:
            if node is None:
                raise RuntimeError("LRU list is corrupt")
            out.append(node)
            node = node.next
        return out

    def keys(self) -> List[str]:
        """Return cached filenames from most to least recently used."""
        return [node.name for node in self.entries()]

    def is_dirty(self, name: str) -> bool:
        """Return whether a cached entry exists and has unflushed content."""
        node = self._map.get(name)
        return node is not None and node.dirty

    def policy_diagnostics(self) -> dict[str, int | float | str]:
        """Return counters and configuration reported by the selected policy."""
        return self.policy.diagnostics()

    def __contains__(self, name: object) -> bool:
        return name in self._map

    def __len__(self) -> int:
        return len(self._map)
