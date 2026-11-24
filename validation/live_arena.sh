#!/usr/bin/env bash
# Bring up a fresh arena, run the five live referee checks, and always tear it down.
#
# The containers have fixed names, so a second match would `docker compose down -v` the
# first one's boxes mid-run. Ownership is one flock file (/run/lock/agent-ctf-arena.lock):
# harness/run_match.py takes the Python side of the same lock, this script takes the shell
# side for the whole bring-up/check/teardown window. Two other guards, both measured:
#   * a runner that predates the lock (or a stray `live_match.py`) holds no lock file, so
#     check the process table too instead of tearing its containers down;
#   * the old inline row command passed `-q` to `docker compose up`/`down`, which docker
#     compose rejects with "unknown shorthand flag: 'q'", so the row exited 1 before any
#     test ran (task #455). The lifecycle lives here now, once, with no such flag.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
lock="${CTF_ARENA_LOCK:-/run/lock/agent-ctf-arena.lock}"

# Wait for the lock first: a runner built after this guard holds it for its whole match,
# so waiting here is how a second run serialises instead of tearing the first one down.
exec 9>"$lock"
if ! flock -w 600 9; then
  printf 'arena busy: could not take %s within 600s\n' "$lock" >&2
  exit 3
fi
printf '%s %s live-arena\n' "$$" "$(date -u +%FT%TZ)" >&9 2>/dev/null || true

# A runner that predates the lock (or a stray live_match.py) holds no lock file, so check the
# process table too. Only a python interpreter whose SECOND argument is a runner counts: a
# shell command line or a task description that merely mentions the script is not a match.
scan_foreign() {
  local out=""
  for pid in $(pgrep -f '^(/[^ ]*/)?python[0-9.]* [^ ]*(harness/run_match\.py|validation/live_match\.py)' || true); do
    [ "$pid" = "$$" ] && continue
    # A finished runner whose parent has not reaped it yet is a zombie, not a conflict.
    [ "$(awk '{print $3}' /proc/$pid/stat 2>/dev/null)" = "Z" ] && continue
    # A runner built after this guard is blocked in flock waiting for the lock we now hold:
    # it is serialised, not a conflict. Measured wchan: locks_lock_inode_wait.
    if [ "$(cat /proc/$pid/wchan 2>/dev/null)" = "locks_lock_inode_wait" ]; then
      continue
    fi
    out="$out$(ps -o pid=,args= -p "$pid" 2>/dev/null)
"
  done
  printf '%s' "$out"
}

foreign=$(scan_foreign)
if [ -n "$foreign" ]; then
  # The previous lock holder releases the lock a few ms before it exits; give it that
  # moment before calling it a conflict, so a clean hand-over is not read as a race.
  sleep 3
  foreign=$(scan_foreign)
fi
if [ -n "$foreign" ]; then
  printf 'arena busy: another match already owns the containers; refusing to tear it down\n%s' \
    "$foreign" >&2
  exit 3
fi

cleanup() { docker compose down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Never reuse containers from a previous run: a stale /home/agent/stolen was read as a
# capture once already (match febcefcd). Fresh state is part of the evidence.
docker compose down -v >/dev/null 2>&1 || true
docker compose up -d --build || exit $?
python3 validation/live_match.py
