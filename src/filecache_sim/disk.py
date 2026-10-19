"""Simulated slow backing store."""

from __future__ import annotations

from typing import Dict, List, Optional


class SimulatedDisk:
    """An in-memory 'disk' that counts every read and write."""

    def __init__(self) -> None:
        self._files: Dict[str, str] = {}
        self.reads = 0
        self.writes = 0

    def read(self, name: str) -> Optional[str]:
        """Return file content, or None if the file does not exist."""
        self.reads += 1
        return self._files.get(name)

    def write(self, name: str, content: str) -> None:
        self.writes += 1
        self._files[name] = content

    def create(self, name: str) -> None:
        """Register an empty file (metadata only, not counted as I/O)."""
        self._files.setdefault(name, "")

    def delete(self, name: str) -> None:
        self._files.pop(name, None)

    def exists(self, name: str) -> bool:
        return name in self._files

    def list_files(self) -> List[str]:
        return sorted(self._files)

    def reset_counters(self) -> None:
        self.reads = 0
        self.writes = 0
