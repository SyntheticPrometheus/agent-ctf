#!/usr/bin/env python3
"""Exercise the agent-facing tool layer against a live arena, with no model in the loop.

`validation/bots.py` calls docker directly, so it never touches what the model is actually given.
This runs the real `AgentTools`: the defense-window gate on `shell`, a real command inside the
agent user's box, and `submit_flag` wired to a real Referee. It is the half between "the referee is
correct" and "an LLM match works", and it is deterministic and free.

    sudo python3 validation/test_tools_live.py        # containers must already be up

Exit 0 = every assertion held; 1 = one failed; 2 = the arena is not up.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT))
import referee.referee as R      # noqa: E402
import referee.verify as V       # noqa: E402
import tools as T                # noqa: E402
from match_clock import MatchClock  # noqa: E402

A, B = "ctf_host_a", "ctf_host_b"
OPP_IP = "172.30.0.11"


def main() -> int:
    up = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                        capture_output=True, text=True).stdout
    if A not in up or B not in up:
        print("FATAL: arena not up — docker compose up -d --build", file=sys.stderr)
        return 2

    log = Path(tempfile.mkdtemp(prefix="ctf-tools-")) / "log.jsonl"
    ref = R.Referee(R.Side("A", A), R.Side("B", B), str(log), scoring="elimination",
                    forbid_copies=True, backend=V.HostSnapshot(), strict_integrity=True)
    ref.plant_flags()
    clock = MatchClock("turns", defense_window=1)
    agent = T.AgentTools(A, "A", ref, clock, [OPP_IP, B], logger=lambda *a, **k: None)
    failures = []
    total = 0

    def check(cond, msg):
        nonlocal total
        total += 1
        if not cond:
            failures.append(msg)
        print(("ok   " if cond else "FAIL ") + msg)

    # 1. defense window open (turn 0 <= window): touching the opponent is refused
    out = agent.shell(f"ping -c1 -W1 {OPP_IP}")
    check("defense window still open" in out, "opponent reference blocked in the defense window")
    out = agent.shell("echo hello-from-the-box")
    check("hello-from-the-box" in out, "own-box command runs during the defense window")
    check("agent" in agent.shell("whoami"), "commands run as the unprivileged agent user")

    # 2. window closed: the same command is allowed through to the shell
    clock.current_turn = 2
    out = agent.shell(f"ping -c1 -W1 {OPP_IP}")
    check("defense window still open" not in out, "opponent reference allowed after the window")
    check("1 packets transmitted" in out or "1 received" in out,
          "the opponent is reachable once offense opens (got %r)" % out[:120])

    # 3. submit_flag: own token does nothing, the opponent's token wins
    own = ref.sides["A"].token
    check("rejected" in agent.submit_flag(own), "submitting your own token is rejected")
    opp = ref.sides["B"].token
    msg = agent.submit_flag(opp)
    check("CORRECT" in msg, "submitting the opponent's token wins (got %r)" % msg[:80])
    check(ref.winner == "A", "the referee recorded A as the winner, got %r" % ref.winner)

    print(f"\n{total - len(failures)}/{total} tool-layer assertions held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
