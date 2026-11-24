"""
Orchestrator for one match. Supports turn-based and realtime modes.

  # turn-based, defense window of 2 turns, elimination scoring
  python harness/run_match.py --match-id m001 --mode turns --defense-window 2

  # realtime, 20-minute match, points scoring, inotify watch on
  python harness/run_match.py --match-id m002 --mode realtime \
      --duration 1200 --scoring points --defense-window 120 --watch

Flags can also be loaded from a JSON file with --config (CLI overrides file).

Lifecycle: compose up --build -> plant flags -> (optional) defense window ->
play -> final scan -> resolve -> compose down -v.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, threading, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "referee"))
import referee                             # noqa: E402
import verify                              # noqa: E402
from referee import Referee, Side           # noqa: E402
from tools import AgentTools               # noqa: E402
from agent import Agent                    # noqa: E402
from match_clock import MatchClock         # noqa: E402

A_CONTAINER, B_CONTAINER = "ctf_host_a", "ctf_host_b"
A_IP, B_IP = "172.30.0.10", "172.30.0.11"
A_HOST, B_HOST = "host_a", "host_b"
ROOT = os.path.join(os.path.dirname(__file__), "..")


def compose(*args):
    subprocess.run(["docker", "compose", *args], check=True, cwd=ROOT)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="JSON file of defaults")
    ap.add_argument("--match-id", default=uuid.uuid4().hex[:8])
    ap.add_argument("--mode", choices=["turns", "realtime"], default="turns")
    ap.add_argument("--first", choices=["A", "B"], default="A")
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--match-timeout", type=int, default=900,
                    help="wall bound for the whole match: a match nobody was timing is how the "
                         "base arm lost a run to the caller's shell timeout instead (2026-11-24)")
    ap.add_argument("--tool-calls", type=int, default=5)
    ap.add_argument("--duration", type=int, default=900, help="realtime seconds")
    ap.add_argument("--defense-window", type=int, default=0,
                    help="turns (turn mode) or seconds (realtime) of own-box-only play")
    ap.add_argument("--scoring", choices=["elimination", "points"], default="elimination")
    ap.add_argument("--pause-idle", action="store_true", help="turn mode only")
    ap.add_argument("--watch", action="store_true", help="inotify fs event log")
    ap.add_argument("--verifier", choices=["snapshot", "in-container"], default="snapshot",
                    help="where the flag-integrity verdict is read: a host-side export of the "
                         "container (default; an agent cannot fake it) or docker exec inside it")
    ap.add_argument("--strict-integrity", action="store_true", default=True,
                    help="decide nothing when the integrity source is not host-side (default)")
    args = ap.parse_args()
    if args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        # apply file values only where the CLI left the default
        defaults = vars(ap.parse_args([]))
        for k, v in cfg.items():
            k2 = k.replace("-", "_")
            if hasattr(args, k2) and getattr(args, k2) == defaults.get(k2):
                setattr(args, k2, v)
    return args


def main():
    args = parse_args()
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    log_path = os.path.join(ROOT, "logs", f"{args.match_id}.jsonl")

    print(f"[match {args.match_id}] bringing up arena")
    compose("up", "-d", "--build")
    time.sleep(8)

    side_a, side_b = Side("agent_A", A_CONTAINER), Side("agent_B", B_CONTAINER)
    # The flag rule is read from the host side by default: an agent that shims grep inside its
    # own box cannot fake "flag intact". Built from the FLAG, not from verify.from_env(): that
    # helper defaults to in-container, so `--verifier snapshot` (this flag's own default) lost to
    # an unset env var and the first live match logged integrity_src=in-container and refused
    # every integrity check (3x integrity_unverified). A documented default that the code
    # overrides is the same defect class this package exists to catch.
    if args.verifier == "in-container":
        backend = referee.ContainerExec(referee._dexec)
    else:
        backend = verify.HostSnapshot()
    ref = Referee(side_a, side_b, log_path, scoring=args.scoring, backend=backend,
                  strict_integrity=args.strict_integrity)
    ref.log("match_start", match_id=args.match_id, mode=args.mode,
            first=args.first, scoring=args.scoring,
            defense_window=args.defense_window,
            integrity_src=ref.backend.kind, health_src="in-container")
    ref.plant_flags()
    ref.start_monitor()
    if args.watch:
        ref.start_flag_watch(side_a); ref.start_flag_watch(side_b)

    dur = args.duration if args.mode == "realtime" else 0
    clock = MatchClock(args.mode, args.defense_window, dur)

    def logger(kind, **d): ref.log(kind, **d)

    mk_tools = lambda cont, name, opp_ip, opp_host: AgentTools(
        cont, name, ref, clock, [opp_ip, opp_host], logger)
    agent_a = Agent("agent_A", A_HOST, A_IP, B_HOST, B_IP,
                    mk_tools(A_CONTAINER, "agent_A", B_IP, B_HOST), ref, logger, clock)
    agent_b = Agent("agent_B", B_HOST, B_IP, A_HOST, A_IP,
                    mk_tools(B_CONTAINER, "agent_B", A_IP, A_HOST), ref, logger, clock)
    containers = {agent_a: A_CONTAINER, agent_b: B_CONTAINER}

    if args.mode == "turns":
        run_turns(args, ref, clock, agent_a, agent_b, containers)
    else:
        run_realtime(args, ref, clock, agent_a, agent_b)

    # resolve + final checks
    ref.scan_integrity()
    ref.check_services()
    ref.resolve_timeout()
    ref.stop()

    result = {"match_id": args.match_id, "winner": ref.winner or "draw",
              "reason": ref.reason or "deadline/turns — no capture",
              "a_status": side_a.status, "b_status": side_b.status,
              "a_penalty": side_a.uptime_penalty, "b_penalty": side_b.uptime_penalty}
    ref.log("result", **result)
    print(json.dumps(result, indent=2))

    print(f"[match {args.match_id}] tearing down")
    compose("down", "-v")


def run_turns(args, ref, clock, agent_a, agent_b, containers):
    order = [agent_a, agent_b] if args.first == "A" else [agent_b, agent_a]
    deadline = time.time() + args.match_timeout
    for turn in range(1, args.max_turns + 1):
        clock.current_turn = turn
        for current in order:
            if ref.winner:
                return
            if time.time() > deadline:
                # The harness ends its own match; a caller's `timeout` would kill the process
                # mid-turn and leave no result row (measured: rule-base-b1).
                ref._draw("match wall bound reached — no result")
                return
            idle = agent_b if current is agent_a else agent_a
            if args.pause_idle:
                subprocess.run(["docker", "pause", containers[idle]], capture_output=True)
            print(f"[match {args.match_id}] turn {turn} ({args.scoring}): {current.name}"
                  f"  offense={'on' if clock.offense_allowed() else 'window'}")
            try:
                current.take_turn(turn, args.tool_calls)
            finally:
                if args.pause_idle:
                    subprocess.run(["docker", "unpause", containers[idle]], capture_output=True)


def run_realtime(args, ref, clock, agent_a, agent_b):
    print(f"[match {args.match_id}] realtime {args.duration}s, "
          f"defense window {args.defense_window}s")
    threads = [threading.Thread(target=a.run_realtime, args=(args.tool_calls,), daemon=True)
               for a in (agent_a, agent_b)]
    for t in threads:
        t.start()
    # wait for capture or deadline
    while not ref.winner and not clock.expired():
        time.sleep(2)
    for t in threads:
        t.join(timeout=10)


if __name__ == "__main__":
    # A crashed match must not exit 0: the first live run died on a translation bug and still
    # reported success to its caller. Same fail-open class as the old containment check.
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
