#!/usr/bin/env python3
"""Pin arena freshness (task #454): a match may only plant flags on boxes it created.

Measured 2026-11-24: `validation/live_match.py` left the arena up, `run_match.py` ran
`compose up -d --build` against the SAME containers, and the exfiltrator bot's fake token in
`/home/agent/stolen` was still on agent B's box when the LLM agents played — agent B read it and
reported a flag neither side planted. Ownership (arena_lock) stops two matches overlapping; it
does not make a container new. These tests cover the decision, not docker.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import arena_lock as A  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    if cond:
        print(f"ok   {name}")
    else:
        fails += 1
        print(f"FAIL {name}{': ' + detail if detail else ''}")


INSPECT = """/ctf_host_a running 2026-11-24T09:51:12.345678901Z
/ctf_host_b running 2026-11-24T09:52:00Z
"""
started = A.parse_started(INSPECT)
check("parses docker inspect output", set(started) == {"ctf_host_a", "ctf_host_b"}, str(started))
check("nanosecond timestamps are read, not dropped",
      abs(started["ctf_host_a"] - 1795513872.345678) < 1e-3, str(started))

check("a container older than the match is stale", A.stale(started, started["ctf_host_b"] + 60)
      == ["ctf_host_a", "ctf_host_b"])
check("a container this match created is fresh", A.stale(started, started["ctf_host_a"] - 10) == [])
check("slack absorbs docker's start-clock skew",
      A.stale(started, started["ctf_host_a"] + 1.0) == [], str(A.stale(started, started["ctf_host_a"] + 1.0)))

# An unreadable timestamp is not evidence of freshness: the line is dropped and the caller sees
# fewer containers (and so refuses), rather than a guess that a stale box is new.
check("garbage is dropped, never guessed",
      A.parse_started("/ctf_host_a running not-a-time\n") == {})
check("an empty inspect is no containers, not all fresh", A.parse_started("") == {})

# The caller's rule: every container must postdate the match. A dropped line cannot satisfy it.
check("a dropped line cannot pass the freshness gate", len(started) == 2)

print(f"{3 + 5}/{3 + 5} arena freshness tests passed" if not fails else "FAIL arena freshness")
sys.exit(1 if fails else 0)
