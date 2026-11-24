#!/usr/bin/env python3
"""The integrity scan must read tmpfs too: `docker export` cannot carry it.

Measured 2026-11-27 (task #451): on a live arena the exfiltrator copied host_a's flag into
host_b's /tmp and the referee scored the match "legal". docker-compose gives /tmp a 64m tmpfs
and docker gives /dev/shm one by default, and `docker export` streams the ROOT filesystem only —
so a token in either was invisible to find_token(), i.e. the referee could not lose a capture.
The fix reads them through /proc/<pid>/root (the host kernel's view of the container's mount
namespace), and this test pins the three ways that read can go wrong: a mount point parsed
wrongly, a token split across the read chunk, and a truncated scan read as "no copy".

No docker needed: the helpers are pure and the tree is a temp directory.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import referee.verify as V  # noqa: E402

TOKEN = b"FLAG{in-a-tmpfs}"

# A real mountinfo shape: root overlay, the two tmpfs mounts docker makes, an escaped space,
# and /proc which must never be walked (it is kernel state, not a place to hold a copy).
MOUNTINFO = """
23 1 0:21 / / rw,relatime - overlay overlay rw,lowerdir=/var/lib/docker/overlay2/l/AAA
24 23 0:22 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
25 23 0:23 / /sys ro,nosuid,nodev,noexec,relatime - sysfs sysfs ro
26 23 0:24 / /tmp rw,nosuid,nodev - tmpfs tmpfs rw,size=65536k
27 23 0:25 / /dev/shm rw,nosuid,nodev - tmpfs shm rw,size=65536k,nr_inodes=1048576
28 23 0:26 / /my\\040dir rw - tmpfs tmpfs rw
"""


def main() -> int:
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    # 1. mount points: tmpfs only, '/' not included, an escaped space unescaped, /proc skipped
    mps = V.tmpfs_mountpoints(MOUNTINFO)
    check(mps == ["/tmp", "/dev/shm", "/my dir"],
          "tmpfs mount points must be %r, got %r" % (["/tmp", "/dev/shm", "/my dir"], mps))
    check(V.tmpfs_mountpoints("") == [], "empty mountinfo must give no mounts")
    check(V.tmpfs_mountpoints("garbage without separator") == [],
          "a malformed line must be skipped, not guessed at")

    with tempfile.TemporaryDirectory(prefix="tmpfs-reader-") as td:
        base = Path(td)
        (base / "stolen").write_text(TOKEN.decode() + "\n")
        (base / "deep" / "nested").mkdir(parents=True)
        (base / "deep" / "nested" / "copy").write_text("x" + TOKEN.decode() + "y")
        (base / "clean").write_text("nothing here\n")

        # 2. labels are container-absolute and every holding file is reported
        hits, used = V._scan_tree(base, TOKEN, V.MAX_SEARCH_BYTES)
        check(hits == ["/deep/nested/copy", "/stolen"],
              "hits must be %r, got %r" % (["/deep/nested/copy", "/stolen"], hits))
        check(used > 0, "the scan must report the bytes it read, got %r" % (used,))

        # 3. a token split across the chunk boundary is still found (the carry logic)
        old_chunk = V.SEARCH_CHUNK
        V.SEARCH_CHUNK = 4
        try:
            hits, _ = V._scan_tree(base, TOKEN, V.MAX_SEARCH_BYTES)
        finally:
            V.SEARCH_CHUNK = old_chunk
        check(hits == ["/deep/nested/copy", "/stolen"],
              "a token spanning a chunk boundary must be found, got %r" % (hits,))

        # 4. a symlink is not a holding file (it would answer from host state, not storage)
        (base / "link").symlink_to(base / "stolen")
        hits, _ = V._scan_tree(base, TOKEN, V.MAX_SEARCH_BYTES)
        check("/link" not in hits, "a symlink must not be reported as a copy, got %r" % (hits,))

        # 5. past the budget the read REFUSES: an empty answer would read as "no copy"
        try:
            V._scan_tree(base, TOKEN, budget=4)
        except V.Unavailable as e:
            check("partial scan is not evidence" in str(e),
                  "refusal must name the reason, got %r" % (str(e),))
        else:
            failures.append("a scan past its budget must raise, not answer")

    if failures:
        for f in failures:
            print("FAIL", f)
        return 1
    print("ok   %s" % Path(__file__).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
