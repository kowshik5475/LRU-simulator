"""Command-line interface: `filecache-sim demo` and `filecache-sim shell`."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .cache import LRUFileCache
from .disk import SimulatedDisk


def _log(msg: str) -> None:
    print("   " + msg)


def show(cache: LRUFileCache) -> None:
    parts = [f"[{e.name}:{e.size}B{'*' if e.dirty else ''}]" for e in cache.entries()]
    body = " ".join(parts) if parts else "(empty)"
    print(f"   MRU -> {body} <- LRU")
    print(f"   Usage: {cache.used_bytes} / {cache.capacity_bytes} bytes   (* = dirty)")


def print_stats(cache: LRUFileCache) -> None:
    s, d = cache.stats, cache.disk
    print("   ---- Statistics ----")
    print(f"   Hits: {s.hits}  Misses: {s.misses}  Hit ratio: {s.hit_ratio * 100:.1f}%")
    print(f"   Evictions: {s.evictions}  Write-backs: {s.write_backs}")
    print(f"   Disk reads: {d.reads}  Disk writes: {d.writes}")


def run_command(cache: LRUFileCache, line: str) -> bool:
    """Execute one shell command. Returns False when the user wants to exit."""
    parts = line.strip().split(None, 2)
    if not parts:
        return True
    cmd = parts[0].lower()
    if cmd == "read":
        if len(parts) < 2:
            print("   usage: read <file>")
        else:
            content = cache.read(parts[1])
            if content is not None:
                print("   content:", content[:30] + "..." if len(content) > 30 else content)
    elif cmd == "write":
        if len(parts) < 3:
            print("   usage: write <file> <content>")
        else:
            cache.write(parts[1], parts[2])
    elif cmd == "delete":
        if len(parts) < 2:
            print("   usage: delete <file>")
        else:
            cache.delete(parts[1])
    elif cmd == "flush":
        cache.flush()
    elif cmd == "show":
        show(cache)
    elif cmd == "stats":
        print_stats(cache)
    elif cmd == "ls":
        print("   disk:", cache.disk.list_files())
    elif cmd == "help":
        print("   read <f> | write <f> <text> | delete <f> | flush | show | stats | ls | exit")
    elif cmd in ("exit", "quit"):
        return False
    else:
        print("   unknown command (type 'help')")
    return True


def demo(capacity: int = 120) -> None:
    disk = SimulatedDisk()
    for name, ch, n in [("notes.txt", "x", 40), ("app.log", "y", 50),
                        ("photo.jpg", "z", 60), ("config.ini", "c", 20)]:
        disk.write(name, ch * n)
    disk.reset_counters()  # don't count the initial setup

    cache = LRUFileCache(capacity, disk, on_event=_log)
    print(f"=== LRU File Cache Demo (capacity {capacity} bytes) ===\n")
    steps = [
        "read notes.txt", "read app.log", "read notes.txt", "read photo.jpg",
        "write config.ini NEWCONFIG=1", "read app.log", "read notes.txt", "flush",
    ]
    for step in steps:
        print("> " + step)
        run_command(cache, step)
        show(cache)
        print()
    print_stats(cache)


def shell(capacity: int) -> None:
    cache = LRUFileCache(capacity, SimulatedDisk(), on_event=_log)
    print(f"LRU file cache shell (capacity {capacity} bytes). Type 'help' for commands.")
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not run_command(cache, line):
            break
    cache.flush()
    print_stats(cache)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="filecache-sim", description="LRU-based file cache simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="run the scripted demonstration")
    p_demo.add_argument("-c", "--capacity", type=int, default=120,
                        help="cache capacity in bytes (default: 120)")

    p_shell = sub.add_parser("shell", help="start an interactive shell")
    p_shell.add_argument("-c", "--capacity", type=int, default=100,
                         help="cache capacity in bytes (default: 100)")

    args = parser.parse_args(argv)
    if args.capacity <= 0:
        parser.error("capacity must be positive")
    if args.command == "demo":
        demo(args.capacity)
    else:
        shell(args.capacity)
    return 0


if __name__ == "__main__":
    sys.exit(main())
