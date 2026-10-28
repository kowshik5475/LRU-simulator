"""In-memory simulated backing store; never accesses the host filesystem."""

from __future__ import annotations

from typing import Dict, List, Optional


class SimulatedDisk:
    """A dictionary-backed disk that counts content reads and writes.

    ``create`` and ``delete`` are metadata operations and do not affect the I/O
    counters. ``read`` counts every lookup, including a lookup for a missing
    file. ``write`` counts every content persistence operation.
    """

    def __init__(self) -> None:
        self._files: Dict[str, str] = {}
        self.reads = 0
        self.writes = 0

    def read(self, name: str) -> Optional[str]:
        """Return content or ``None`` when absent; increment reads in either case."""
        self.reads += 1
        return self._files.get(name)

    def write(self, name: str, content: str) -> None:
        """Persist content in simulated memory and increment the write counter."""
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        self.writes += 1
        self._files[name] = content

    def create(self, name: str) -> None:
        """Register an empty file without counting a content I/O operation."""
        self._files.setdefault(name, "")

    def delete(self, name: str) -> None:
        """Remove a file if present; deleting a missing file is a no-op."""
        self._files.pop(name, None)

    def exists(self, name: str) -> bool:
        """Return whether a file is registered, including an empty file."""
        return name in self._files

    def list_files(self) -> List[str]:
        """Return registered filenames in sorted order."""
        return sorted(self._files)

    def reset_counters(self) -> None:
        """Reset read/write counters without changing simulated file contents."""
        self.reads = 0
        self.writes = 0
