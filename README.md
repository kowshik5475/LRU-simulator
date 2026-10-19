# LRU File Cache Simulator

A mini-OS demonstration of how a file/page cache can be managed with an
**LRU (Least Recently Used)** eviction strategy. It extends classic LRU-cache /
HashSet exercises with byte-based capacity, a simulated disk, and a
write-back policy.

## How it works

| Piece | Purpose |
|-------|---------|
| `LRUFileCache` | `dict` for O(1) lookup + hand-written doubly linked list for recency order (MRU at head, LRU at tail) |
| `SimulatedDisk` | Slow backing store that counts reads and writes |
| Write-back policy | Writes only mark the cached entry *dirty*; the disk is updated on eviction or `flush()` |
| Byte capacity | One large file may evict several small ones; files larger than the cache bypass it |
| `CacheStats` | Hits, misses, hit ratio, evictions, write-backs |

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
filecache-sim demo              # scripted walk-through
filecache-sim demo -c 200       # custom capacity
filecache-sim shell -c 100      # interactive shell
python -m filecache_sim demo    # without installing the script
```

Shell commands: `read <f>`, `write <f> <text>`, `delete <f>`, `flush`,
`show`, `stats`, `ls`, `exit`.

### As a library

```python
from filecache_sim import LRUFileCache, SimulatedDisk

disk = SimulatedDisk()
disk.write("notes.txt", "hello world")

cache = LRUFileCache(capacity_bytes=64, disk=disk, on_event=print)
cache.read("notes.txt")          # MISS -> loaded from disk
cache.read("notes.txt")          # HIT
cache.write("log.txt", "x" * 40) # cached dirty
cache.flush()                    # persist dirty entries
print(cache.stats)
```

## Tests

```bash
pytest
```

## Project layout

```
src/filecache_sim/
    cache.py   # LRUFileCache, CacheStats
    disk.py    # SimulatedDisk
    cli.py     # demo + interactive shell
tests/
```

## Ideas for extension

- Alternative policies (FIFO, LFU, CLOCK) behind a common interface
- Workload generator (e.g. Zipf) and hit-ratio vs. cache-size plots
- Pinned files that cannot be evicted
