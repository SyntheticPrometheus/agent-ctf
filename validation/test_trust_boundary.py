#!/usr/bin/env python3
"""The boundary of the 'host-side' verdict: it is as good as `docker export` on PATH.

HostSnapshot removed the agent from the evidence path — the agent has no code path into a
`docker export` stream. That is not the same as independent verification: a host whose docker
CLI lies (or a substituted `docker`) decides the verdict, and no offline referee can tell. This
test pins that boundary in code, so the claim cannot creep from "not capturable by the agent"
to "true", and pins the path labels the verdict quotes, since a host-supplied member name is
attacker-shaped data too.
"""
import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import referee.verify as V  # noqa: E402

TOKEN = "FLAG{boundary}"
FLAG = "/home/agent/flag.txt"


def write_tar(path: Path, members):
    with tarfile.open(path, "w") as tf:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


def with_fake_docker(tar_path: Path, fn):
    """Run fn() with a `docker` on PATH that can only export tar_path."""
    with tempfile.TemporaryDirectory(prefix="boundary-bin-") as bd:
        script = Path(bd) / "docker"
        script.write_text('#!/bin/sh\nif [ "$1" = export ]; then exec cat %s; fi\n'
                          'echo "fake docker: unsupported: $*" >&2; exit 1\n' % tar_path)
        script.chmod(0o755)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bd}:{old}"
        try:
            return fn()
        finally:
            os.environ["PATH"] = old


def main() -> int:
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="boundary-tar-") as td:
        td = Path(td)

        # 1. the CLI decides: the same referee reads a present flag as present ...
        honest = td / "honest.tar"
        write_tar(honest, [("./home/agent/flag.txt", (TOKEN + "\n").encode())])
        hits = with_fake_docker(honest, lambda: V.HostSnapshot().find_token("ctf_a", TOKEN))
        check(hits == [FLAG], "a plain export must read as %r, got %r" % ([FLAG], hits))

        # ... and a forged export that omits the flag reads as deleted (a forfeit).
        forged = td / "forged.tar"
        write_tar(forged, [("./home/agent/flag.txt", b"nothing here\n")])
        hits = with_fake_docker(forged, lambda: V.HostSnapshot().find_token("ctf_a", TOKEN))
        check(hits == [], "the verdict follows the export, got %r" % (hits,))

        # 2. labels: './' collapses, doubled slashes collapse, and the result is absolute
        odd = td / "odd.tar"
        write_tar(odd, [("././home//agent/flag.txt", (TOKEN + "\n").encode())])
        hits = with_fake_docker(odd, lambda: V.HostSnapshot().find_token("ctf_a", TOKEN))
        check(hits == [FLAG], "member names must normalise to %r, got %r" % ([FLAG], hits))

        # 3. a member that escapes the root is not a path: refuse the stream, do not alias it
        escape = td / "escape.tar"
        write_tar(escape, [("/../../etc/flag", (TOKEN + "\n").encode())])
        try:
            with_fake_docker(escape, lambda: V.HostSnapshot().find_token("ctf_a", TOKEN))
        except V.Unavailable as e:
            check("escaping the root" in str(e), "refusal must name the reason, got %r" % (str(e),))
        else:
            failures.append("an export with '../' must be refused, not read")

    if failures:
        for f in failures:
            print("FAIL", f)
        return 1
    print("ok   %s" % Path(__file__).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
