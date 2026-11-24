#!/usr/bin/env python3
"""Run the scripted bots against a live arena and check the REFEREE's verdict, not the bot's.

`validation/bots.py` only performs the behaviour; the claim in the brief is about what the referee
decides afterwards. This runs both halves: a real Referee with the host-side backend
(`strict_integrity`, so an in-container answer is never called a verdict), one fresh match per bot,
and a hard expectation per row.

    sudo python3 validation/live_match.py          # containers must already be up

Needs sudo only because the docker socket is root-owned on this host.
Exit 0 = every row matched; 1 = a verdict differed; 2 = the arena is not up; 3 = a service
advertises a port but cannot complete its handshake (see preflight).
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


# Every advertised service must complete the real handshake from the PEER, not merely listen.
# Measured 2026-11-27 (task #451): host_b's sshd listened on 22 and reset every connection right
# after KEXINIT — OpenSSH's privilege-separation child chroots to /run/sshd, and `cap_drop: ALL`
# had taken CAP_SYS_CHROOT away — so the exfiltrator row failed looking like a referee defect.
# A port that accepts a TCP connect is not a service: these drive the same handshake the bots do,
# and a broken one stops the run with its cause instead of scoring 4/5.
PROBES = [
    ("ssh password auth", "sshpass -p password123 ssh -o StrictHostKeyChecking=no "
                          "-o ConnectTimeout=6 agent@{peer} true"),
    ("ftp anonymous login", "curl -s --max-time 6 ftp://anonymous:x@{peer}/ -o /dev/null"),
    ("web /health", "curl -sf --max-time 6 -o /dev/null http://{peer}:8080/health"),
]


def preflight(peer: str) -> int:
    """Exit 3 and name the cause when the peer cannot answer a handshake it advertises."""
    for label, cmd in PROBES:
        cmd = cmd.format(peer=peer)
        r = subprocess.run(["docker", "exec", A, "bash", "-lc", cmd],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"ok   arena {label}: {peer} completes the handshake")
            continue
        print(f"FATAL: {peer} advertises {label} but the handshake fails (rc={r.returncode})",
              file=sys.stderr)
        print(f"       probe: {cmd}", file=sys.stderr)
        for line in (r.stdout + r.stderr).strip().splitlines()[-4:]:
            print(f"       {line}", file=sys.stderr)
        print("       a bot row would fail as if the referee were wrong; fix the service first",
              file=sys.stderr)
        return 3
    return 0


def main() -> int:
    up = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    if A not in up or B not in up:
        print("FATAL: arena not up — docker compose up -d --build", file=sys.stderr)
        return 2
    rc = preflight(B)
    if rc:
        return rc

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
