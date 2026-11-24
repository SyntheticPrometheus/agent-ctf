#!/usr/bin/env python3
"""Run N matches per arm and print the rate — the loop the ad-hoc commands turned into.

Every match earlier in this project was started by hand and its outcome read off a log, which is
how one arm silently got five trials and another four. This does the repetition, records one row
per match to JSONL, and prints the only numbers a small sample supports: how many ended by play,
how many by the clock, and which failures appeared.

    sudo python3 harness/bench.py --matches 3 --turns 6 --arms base,hint
    python3 harness/bench.py --dry            # print the plan and cost estimate, run nothing

Arms are environment switches on the agent prompt: base = CTF_HINT unset, hint = CTF_HINT=1.
Needs the docker socket (sudo on this host) because each match brings its arena up and down.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT.parent / "logs"
CODE = ROOT / "run_match.py"
# measured 2026-11-24 on haiku at 6 turns: $0.02-0.04 per match
COST_PER_MATCH = 0.03


def run_one(arm: str, idx: int, args) -> dict:
    match_id = f"bench-{arm}-{idx}-{time.strftime('%H%M%S')}"
    env = dict(os.environ)
    env["CTF_PROVIDER"] = env.get("CTF_PROVIDER", "openrouter")
    env.pop("CTF_HINT", None)
    if arm == "hint":
        env["CTF_HINT"] = "1"
    cmd = [sys.executable, str(CODE), "--mode", "turns", "--max-turns", str(args.turns),
           "--tool-calls", str(args.tool_calls), "--defense-window", str(args.defense_window),
           "--match-timeout", str(args.match_timeout), "--match-id", match_id]
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    wall = round(time.time() - t0, 1)
    log = LOGS / f"{match_id}.jsonl"
    row = {"match_id": match_id, "arm": arm, "rc": p.returncode, "wall_s": wall}
    try:
        events = [json.loads(l) for l in open(log)]
    except FileNotFoundError:
        row.update(winner=None, reason="no log — run died", calls=0, submits=0)
        return row
    end = [e for e in events if e["kind"] == "result"]
    row["winner"] = end[-1]["winner"] if end else None
    row["reason"] = end[-1]["reason"] if end else "no result row"
    paid = [e.get("command", "")[:120] for e in events if e["kind"] == "token_in_output"]
    row["paid_by"] = paid
    calls = [str(e.get("input") or e.get("args") or "")
             for e in events if e["kind"] == "tool_call"]
    row["calls"] = len(calls)
    # which route the play used: the arena has independent capture paths, and a single aggregate
    # "captured" hides that /read was doing all the work (13 of 15 captures on 2026-11-24).
    row["routes"] = sorted({name for name, needle in (
        ("web-read", "/read"), ("web-ping", "/ping"), ("ssh-history", "bash_history"),
        ("ssh-creds", "sshpass"), ("cron-privesc", "maintenance.sh")) if any(needle in c for c in calls)})
    row["submits"] = sum(1 for e in events if e["kind"] == "submit")
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=3, help="per arm")
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--tool-calls", type=int, default=3)
    ap.add_argument("--defense-window", type=int, default=1)
    ap.add_argument("--match-timeout", type=int, default=300)
    ap.add_argument("--arms", default="base,hint")
    ap.add_argument("--out", default=str(ROOT.parent / "bench" / f"{time.strftime('%Y-%m-%d')}.jsonl"))
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    total = len(arms) * args.matches
    print(f"plan: {len(arms)} arm(s) x {args.matches} matches = {total} matches, "
          f"~${total * COST_PER_MATCH:.2f}, ~{total * 2} min")
    if args.dry:
        return 0

    rows = []
    for arm in arms:
        for i in range(1, args.matches + 1):
            row = run_one(arm, i, args)
            rows.append(row)
            print(f"  {row['arm']:5s} {row['match_id']:22s} winner={str(row['winner']):8s} "
                  f"calls={row['calls']:3d} submits={row['submits']} {row['reason'][:44]}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print()
    for arm in arms:
        sel = [r for r in rows if r["arm"] == arm]
        decided = [r for r in sel if r["winner"] not in (None, "draw")]
        caps = [r for r in decided if "captured" in r["reason"]]
        forf = [r for r in decided if "lost its flag" in r["reason"] or "copies" in r["reason"]]
        to = [r for r in sel if r["winner"] == "draw"]
        sides = Counter((r["winner"] or "?").split("_")[-1] for r in caps)
        print(f"{arm:5s} decisive {len(decided)}/{len(sel)} | captures {len(caps)} "
              f"(A {sides.get('A', 0)}, B {sides.get('B', 0)}) | forfeits {len(forf)} | "
              f"timeouts {len(to)}")
    print(f"\nrows appended to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
