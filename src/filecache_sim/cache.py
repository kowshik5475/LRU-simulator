"""LRU file cache: hash map + hand-written doubly linked list.

* Capacity is measured in bytes (1 character == 1 byte).
* Write-back policy: writes mark an entry dirty; the disk is updated on
  eviction or an explicit flush().
* Every operation is O(1), except eviction/flush which are O(evicted/dirty).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .disk import SimulatedDisk

EventHandler = Callable[[str], None]


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    write_backs: int = 0

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class _Node:
    __slots__ = ("name", "content", "dirty", "prev", "next")

    def __init__(self, name: str, content: str, dirty: bool = False) -> None:
        self.name = name
        self.content = content
        self.dirty = dirty
        self.prev: Optional[_Node] = None
        self.next: Optional[_Node] = None

    @property
    def size(self) -> int:
        return len(self.content)


class LRUFileCache:
    def __init__(
        self,
        capacity_bytes: int,
        disk: SimulatedDisk,
        on_event: Optional[EventHandler] = None,
    ) -> None:
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self.capacity_bytes = capacity_bytes
        self.used_bytes = 0
        self.disk = disk
        self.stats = CacheStats()
        self._emit: EventHandler = on_event or (lambda _msg: None)

        self._map: Dict[str, _Node] = {}
        self._head = _Node("HEAD", "")  # MRU sentinel
        self._tail = _Node("TAIL", "")  # LRU sentinel
        self._head.next = self._tail
        self._tail.prev = self._head

    # ------------------------------------------------------ list helpers
    def _unlink(self, n: _Node) -> None:
        n.prev.next = n.next
        n.next.prev = n.prev

    def _push_front(self, n: _Node) -> None:
        n.next = self._head.next
        n.prev = self._head
        self._head.next.prev = n
        self._head.next = n

    def _touch(self, n: _Node) -> None:
        self._unlink(n)
        self._push_front(n)

    def _remove(self, name: str) -> Optional[_Node]:
        n = self._map.pop(name, None)
        if n:
            self._unlink(n)
            self.used_bytes -= n.size
        return n

    # ----------------------------------------------------------- internals
    def _evict_until_fits(self, needed: int) -> None:
        while self.used_bytes + needed > self.capacity_bytes and self._tail.prev is not self._head:
            victim = self._tail.prev
            self._remove(victim.name)
            self.stats.evictions += 1
            note = ""
            if victim.dirty:
                self.disk.write(victim.name, victim.content)
                self.stats.write_backs += 1
                note = " (dirty -> written back to disk)"
            self._emit(f"[EVICT] {victim.name} ({victim.size}B){note}")

    def _insert(self, name: str, content: str, dirty: bool) -> None:
        if len(content) > self.capacity_bytes:
            self._emit(f"[BYPASS] {name} larger than cache; going straight to disk")
            if dirty:
                self.disk.write(name, content)
            return
        self._evict_until_fits(len(content))
        node = _Node(name, content, dirty)
        self._push_front(node)
        self._map[name] = node
        self.used_bytes += node.size

    # -------------------------------------------------------- public API
    def read(self, name: str) -> Optional[str]:
        """Return file content, or None if it exists nowhere."""
        node = self._map.get(name)
        if node:
            self.stats.hits += 1
            self._touch(node)
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
        """Write-back: update the cache now, the disk on eviction/flush."""
        self._remove(name)
        self._emit(f"[WRITE] {name} ({len(content)}B) cached as dirty")
        self.disk.create(name)
        self._insert(name, content, dirty=True)

    def delete(self, name: str) -> None:
        self._remove(name)
        self.disk.delete(name)
        self._emit(f"[DELETE] {name}")

    def flush(self) -> None:
        """Write all dirty entries to disk (like sync())."""
        n = self._head.next
        while n is not self._tail:
            if n.dirty:
                self.disk.write(n.name, n.content)
                n.dirty = False
                self.stats.write_backs += 1
                self._emit(f"[FLUSH] {n.name}")
            n = n.next

    # ------------------------------------------------------ introspection
    def entries(self) -> List[_Node]:
        """Cache entries ordered from most to least recently used."""
        out, n = [], self._head.next
        while n is not self._tail:
            out.append(n)
            n = n.next
        return out

    def keys(self) -> List[str]:
        return [n.name for n in self.entries()]

    def is_dirty(self, name: str) -> bool:
        return name in self._map and self._map[name].dirty

    def __contains__(self, name: object) -> bool:
        return name in self._map

    def __len__(self) -> int:
        return len(self._map)
