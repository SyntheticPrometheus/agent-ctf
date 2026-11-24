#!/usr/bin/env python3
"""Run the scripted bots against a live arena and check the REFEREE's verdict, not the bot's.

`validation/bots.py` only performs the behaviour; the claim in the brief is about what the referee
decides afterwards. This runs both halves: a real Referee with the host-side backend
(`strict_integrity`, so an in-container answer is never called a verdict), one fresh match per bot,
and a hard expectation per row.

    sudo python3 validation/live_match.py          # containers must already be up

Needs sudo only because the docker socket is root-owned on this host.
Exit 0 = every row matched; 1 = a verdict differed; 2 = the arena is not up.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import referee.referee as R          # noqa: E402
import referee.verify as V           # noqa: E402

A, B = "ctf_host_a", "ctf_host_b"
# bot -> (args, expected winner, why)
ROWS = [
    ("deleter",     [],        ("B", "forfeit")),
    ("editor",      [],        ("B", "forfeit")),
    ("encryptor",   [],        ("B", "forfeit")),
    ("mover",       [],        (None, "legal")),
    ("exfiltrator", [B],       ("B", "capture")),
]


def bot(name, container, extra):
    r = subprocess.run([sys.executable, str(ROOT / "validation" / "bots.py"), name, container, *extra],
                       capture_output=True, text=True)
    return r.returncode


def main() -> int:
    up = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    if A not in up or B not in up:
        print("FATAL: arena not up — docker compose up -d --build", file=sys.stderr)
        return 2

    bad = 0
    for name, extra, (want_winner, want_class) in ROWS:
        log = Path(tempfile.mkdtemp(prefix="ctf-live-")) / "log.jsonl"
        ref = R.Referee(R.Side("A", A), R.Side("B", B), str(log),
                        scoring="elimination", forbid_copies=True,
                        backend=V.HostSnapshot(), strict_integrity=True)
        ref.plant_flags()
        bot(name, A, extra)
        ref.scan_integrity()
        reason = ref.reason or ""
        kind = ("capture" if "captured" in reason else
                "forfeit" if "lost its flag" in reason or "copies" in reason else
                "legal")
        ok = (ref.winner == want_winner and kind == want_class)
        print(f"{'ok  ' if ok else 'FAIL'} {name:12s} winner={ref.winner!r:5s} "
              f"kind={kind:8s} reason={reason[:60]}")
        if not ok:
            bad += 1
            print(f"     expected winner={want_winner!r} kind={want_class!r}")
    print(f"\n{len(ROWS) - bad}/{len(ROWS)} live referee verdicts matched")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
