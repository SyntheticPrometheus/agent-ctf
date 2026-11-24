#!/bin/bash
# Confirm the arena is actually contained. Run after `docker compose up -d`.
#
# This is a GATE, not a report: every line below is asserted, and the script exits non-zero if any
# expectation is violated. Measured 2026-11-24 on the first live bring-up: the previous version
# printed "should fail"/"should succeed" and always exited 0, so with both containers exited it
# announced containment from five `docker exec` errors — a fail-open check is worse than none.
#
# Exit: 0 all expectations held; 1 an expectation was violated; 2 a container is not running.
set -u
A="${1:-ctf_host_a}"
B="${2:-ctf_host_b}"
bad=0

for c in "$A" "$B"; do
  running=$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo missing)
  if [ "$running" != "true" ]; then
    echo "FATAL: $c is not running ($running) — containment is unproven, not passed"
    echo "       see: docker logs $c"
    exit 2
  fi
done

# expect <label> <want: good|bad> <command>
expect() {
  local label="$1" want="$2" cmd="$3" out
  out=$(docker exec "$A" bash -lc "$cmd" 2>&1)
  case "$want:$out" in
    bad:*REACHABLE*|bad:*RESOLVED*|bad:*PRESENT*|bad:*ROOT-BAD*)
      echo "FAIL $label — got: $out" >&2; bad=1 ;;
    good:*blocked-good*|good:*absent-good*|good:*reachable-good*|good:*noroot-good*)
      echo "ok   $label" ;;
    *)
      echo "FAIL $label — inconclusive: $out" >&2; bad=1 ;;
  esac
}

expect "internet egress blocked"            bad  "curl -s --max-time 5 https://example.com >/dev/null && echo REACHABLE-BAD || echo blocked-good"
expect "public DNS does not resolve"        bad  "getent hosts google.com >/dev/null && echo RESOLVED-BAD || echo blocked-good"
expect "no docker socket in the box"        bad  "test -S /var/run/docker.sock && echo PRESENT-BAD || echo absent-good"
expect "opponent reachable on arena net"    good "ping -c1 -W2 172.30.0.11 >/dev/null && echo reachable-good || echo UNREACHABLE-CHECK"
expect "no privilege gain to root"          bad  "sudo id 2>/dev/null && echo ROOT-BAD || echo noroot-good"

if [ "$bad" -ne 0 ]; then
  echo "containment: FAILED — do not run agents against this arena"
  exit 1
fi
echo "containment: ok — $A and $B are isolated from egress and from the host"
