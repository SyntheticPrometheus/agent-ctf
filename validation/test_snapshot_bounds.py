#!/usr/bin/env python3
"""The integrity scan must see the whole filesystem, not a 512 KB prefix of it.

Measured gap (2026-11-23, round 3): `HostSnapshot.files()` skipped any file larger
than MAX_FILE_BYTES, and `find_token` searched only that dict. So a flag copy
padded past 512 KB was invisible: the copies rule never fired, and a flag moved
into a large file read as "lost" — the opposite verdict, from the same blindness.

The fake `docker` here only has to honour `export`: the snapshot path reads the
stream from the host, which is exactly what this pins.
"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import referee.verify as V  # noqa: E402

TOKEN = "FLAG{big-file-copy}"
SMALL = "/home/agent/flag.txt"
BIG = "/home/agent/notes.bin"


def build_tar(path: Path):
    blob = b"\x00" * 700_000 + TOKEN.encode() + b"\x00" * 1024
    with tarfile.open(path, "w") as tf:
        for name, data in (
            ("./home/agent/flag.txt", TOKEN.encode() + b"\n"),
            ("./home/agent/notes.bin", blob),
        ):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


def fake_docker(bindir: Path, tar_path: Path):
    """A docker that can only export: any other subcommand fails loudly."""
    script = bindir / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = export ]; then exec cat %s; fi\n'
        'echo "fake docker: unsupported: $*" >&2; exit 1\n' % tar_path
    )
    script.chmod(0o755)


def main() -> int:
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="snap-bounds-") as td:
        td = Path(td)
        tar_path = td / "snap.tar"
        bindir = td / "bin"
        bindir.mkdir()
        build_tar(tar_path)
        fake_docker(bindir, tar_path)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bindir}:{old_path}"
        try:
            backend = V.HostSnapshot()
            hits = backend.find_token("ctf_a", TOKEN)
        finally:
            os.environ["PATH"] = old_path

        check(SMALL in hits, "the small flag file must be found, got %r" % (hits,))
        check(BIG in hits,
              "a token past the 512 KB per-file cap must still be found (a padded copy "
              "is a copy), got %r" % (hits,))
        check(len(hits) == 2, "expected exactly two holding files, got %r" % (hits,))

    if failures:
        for f in failures:
            print("FAIL", f)
        return 1
    print("ok   %s" % Path(__file__).name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
