"""One fixed-name arena, one owner at a time.

Both `harness/run_match.py` and `validation/live_arena.sh` drive the same two containers
(`ctf_host_a`, `ctf_host_b`) on the same network. Two runs at once do not merely interfere:
each starts with `docker compose down -v`, so one run tears the other's containers down
mid-match. Measured 2026-11-24: a detached 16-match bench was running while the weekly
live-referee row started; `docker export` was asked for a container that the bench had
already killed and returned "container ... is Dead", crashing live_match with a traceback
that looked like a referee defect.

So ownership is a lock file, not a hope. The shell wrapper takes the same file with
`flock(1)`; this module is the Python side of that one lock.
"""
from __future__ import annotations

import fcntl
import datetime
import os
import sys
import time

LOCK_PATH = os.environ.get("CTF_ARENA_LOCK", "/run/lock/agent-ctf-arena.lock")


class ArenaBusy(RuntimeError):
    """Another match owns the arena and did not release it in time."""


class lock:
    """Exclusive arena ownership for the duration of one match."""

    def __init__(self, timeout: float = 900.0, path: str = LOCK_PATH):
        self.timeout = timeout
        self.path = path
        self.fh = None

    def acquire(self):
        self.fh = open(self.path, "a+")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self.fh.close()
                    self.fh = None
                    raise ArenaBusy(f"{self.path} is held by another arena owner")
                time.sleep(1.0)
        # Name the owner, so a waiting shell wrapper can say who it is waiting for.
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                      f"{os.path.basename(sys.argv[0])}\n")
        self.fh.flush()
        return self

    def release(self):
        if self.fh is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


# ------------------------------------------------------------------ freshness
# Ownership stops two matches overlapping; it does not make a container new. Measured
# 2026-11-24 (task #454): `validation/live_match.py` left the arena up, `run_match.py` then ran
# `compose up -d --build` against the SAME containers, and the exfiltrator bot's fake token
# (`/home/agent/stolen`, written by validation/bots.py) was still there when the LLM agents
# played. Agent B read it and reported a "flag" neither side planted. A match must start from
# containers this run created, and the log must let a reader check that afterwards.

def parse_started(text: str) -> dict[str, float]:
    """`docker inspect -f '{{.Name}} {{.State.Status}} {{.State.StartedAt}}'` lines -> {name: epoch}.

    A line whose timestamp cannot be read is dropped, never guessed: an unreadable age is not
    evidence of freshness, and a guess here is what let a stale box pass as new.
    """
    out: dict[str, float] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        name, stamp = parts[0].lstrip("/"), parts[-1]
        try:
            out[name] = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return out


def stale(started: dict[str, float], match_started: float, slack: float = 2.0) -> list[str]:
    """Containers that were already running when this match began (they predate match_started)."""
    return sorted(n for n, t in started.items() if t < match_started - slack)
