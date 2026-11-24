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

# expect <label> <command>: the probe prints "<something>-good" only in the wanted state, and
# "<something>-BAD" (or UNREACHABLE-CHECK) otherwise. Asserting the suffix keeps the two failure
# modes apart: a violated expectation and an inconclusive probe both fail, but say which.
expect() {
  local label="$1" cmd="$2" out
  out=$(docker exec "$A" bash -lc "$cmd" 2>&1)
  case "$out" in
    *-good)   echo "ok   $label" ;;
    *-BAD*|*UNREACHABLE*) echo "FAIL $label — violated: $out" >&2; bad=1 ;;
    *)        echo "FAIL $label — inconclusive: $out" >&2; bad=1 ;;
  esac
}

expect "internet egress blocked"            "curl -s --max-time 5 https://example.com >/dev/null && echo REACHABLE-BAD || echo blocked-good"
expect "public DNS does not resolve"        "getent hosts google.com >/dev/null && echo RESOLVED-BAD || echo blocked-good"
expect "no docker socket in the box"        "test -S /var/run/docker.sock && echo PRESENT-BAD || echo absent-good"
expect "opponent reachable on arena net"    "ping -c1 -W2 172.30.0.11 >/dev/null && echo reachable-good || echo UNREACHABLE-CHECK"
expect "no privilege gain to root"          "sudo id 2>/dev/null && echo ROOT-BAD || echo noroot-good"

# The capability set is the whole containment argument, so it is pinned, not remembered: every
# entry in docker-compose.yml carries a measured reason (CHOWN vsftpd's log; SETUID/SETGID the
# agent drop; SYS_CHROOT sshd's privsep chroot — without it every SSH connection died at KEXINIT,
# task #451). A new capability must add its reason here in the same commit, and a gutted
# `cap_drop: ALL` cannot pass as a fix for a service that will not start.
WANT_CAPS="[CAP_CHOWN CAP_SETGID CAP_SETUID CAP_SYS_CHROOT]"
for c in "$A" "$B"; do
  got=$(docker inspect -f '{{.HostConfig.CapAdd}}' "$c" 2>/dev/null)
  if [ "$got" = "$WANT_CAPS" ]; then
    echo "ok   capability set is the documented four ($c)"
  else
    echo "FAIL capability set on $c is $got, expected $WANT_CAPS — document the reason in docker-compose.yml" >&2
    bad=1
  fi
done

if [ "$bad" -ne 0 ]; then
  echo "containment: FAILED — do not run agents against this arena"
  exit 1
fi
echo "containment: ok — $A and $B are isolated from egress and from the host"
