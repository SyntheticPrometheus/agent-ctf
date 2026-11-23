#!/bin/bash
# Confirm the arena is actually contained. Run after `docker compose up -d`.
# Every check below should FAIL from inside the container (that is the pass
# condition). If any succeeds, stop and fix isolation before running agents.
set -u
C="${1:-ctf_host_a}"
echo "== containment checks for $C =="

echo -n "internet egress (should fail): "
docker exec "$C" bash -lc "curl -s --max-time 5 https://example.com >/dev/null && echo REACHABLE-BAD || echo blocked-good"

echo -n "DNS to public resolver (should fail): "
docker exec "$C" bash -lc "getent hosts google.com >/dev/null && echo RESOLVED-BAD || echo blocked-good"

echo -n "docker socket present (should be absent): "
docker exec "$C" bash -lc "test -S /var/run/docker.sock && echo PRESENT-BAD || echo absent-good"

echo -n "can reach opponent on arena net (should succeed): "
docker exec "$C" bash -lc "ping -c1 -W2 172.30.0.11 >/dev/null && echo reachable-good || echo UNREACHABLE-CHECK"

echo -n "new-privileges blocked (should fail to gain root): "
docker exec -u agent "$C" bash -lc "sudo id 2>/dev/null && echo ROOT-BAD || echo noroot-good"
