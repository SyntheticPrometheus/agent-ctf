"""Where a verdict comes from decides whether it is evidence.

The referee's three measured bugs (2026-11-23) were all the same class: trusting state the
adversary controls. The deepest one is structural and the three fixes did not touch it — the
integrity scan runs `grep` INSIDE the container, as root, with binaries the agent can replace.
An agent that shims grep to print `/home/agent/flag.txt` keeps "flag intact" forever while the
flag is gone: the referee reads the adversary's own report and calls it a verdict.

Two verdicts, two sources:

  integrity  the authoritative rule ("exactly one readable file holds the exact plaintext
             token") is a statement about the CONTAINER'S FILESYSTEM, so it is read from
             the host side, where the agent has no code path;
  liveness   "is ssh up" can only be answered from inside the box, so it stays an
             in-container probe and is marked capturable rather than trusted.

Backends (`Referee(backend=...)`):

  ContainerExec  today's behaviour: `docker exec` and grep inside. Capturable; kept as the
                 default so a live match does not change silently, and `strict_integrity`
                 refuses to call its answer a verdict.
  HostSnapshot   `docker export <container> | tar -x` into a temp dir, then read and grep
                 locally. Authoritative — the agent's binaries never run in this path.
  LocalDir       offline double over {container: {path: content}}; used by validation/.
  ExecCallable   adapts a bare exec function (the `_dexec` fake in the tests) so the old
                 call style keeps working.

This file is also the seam the live path needs: with docker installed, HostSnapshot replaces
ContainerExec and the referee's integrity verdict stops being capturable state.
"""
from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024      # a snapshot read is bounded: an agent can fill a disk
MAX_FILE_BYTES = 512 * 1024               # ... and can plant a huge file to stall the scan
MAX_SEARCH_BYTES = 256 * 1024 * 1024      # the token search streams; past this it says so
SEARCH_CHUNK = 1 * 1024 * 1024


class Unavailable(Exception):
    """The backend cannot produce this kind of evidence on this host."""


class Backend:
    kind = "?"
    authoritative_integrity = False

    def exec(self, container: str, cmd: list[str], timeout: int = 15,
             input_: str | None = None) -> tuple[int, str]:
        raise NotImplementedError

    def files(self, container: str) -> dict[str, str]:
        """Host-side view of the container's filesystem: path -> text content."""
        raise Unavailable(f"{self.kind} has no host-side view")

    def find_token(self, container: str, token: str) -> list[str]:
        """Paths in the container whose CONTENT holds the token, read host-side."""
        hits = []
        for path, content in self.files(container).items():
            if token in content:
                hits.append(path)
        return sorted(hits)

    def health(self, container: str) -> dict:
        """Liveness probes. In-container by necessity: only the box answers 'is ssh up'."""
        checks = {}
        _, out = self.exec(container, ["bash", "-c",
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health"], timeout=10)
        checks["web"] = out.strip().endswith("200")
        for svc, port in (("ssh", 22), ("ftp", 21)):
            rc, _ = self.exec(container, ["bash", "-c",
                f"timeout 3 bash -c 'echo > /dev/tcp/127.0.0.1/{port}'"], timeout=8)
            checks[svc] = rc == 0
        return checks


class ExecCallable(Backend):
    """Wrap a bare exec callable (docker exec, or a fake) — in-container evidence only."""

    kind = "in-container"

    def __init__(self, fn):
        self._fn = fn

    def exec(self, container, cmd, timeout=15, input_=None):
        return self._fn(container, cmd, timeout=timeout, input_=input_)

    def find_token(self, container, token):
        _, out = self.exec(container, ["bash", "-c",
            "grep -rlF -f - / --binary-files=without-match "
            "--exclude-dir=proc --exclude-dir=sys --exclude-dir=dev 2>/dev/null"],
            timeout=30, input_=token + "\n")
        return [ln for ln in out.splitlines() if ln.strip()]


class ContainerExec(ExecCallable):
    """The default: `docker exec` inside the container. Never authoritative for integrity."""

    kind = "in-container"


class LocalDir(Backend):
    """Offline double: the filesystem is a dict. Authoritative, so tests can prove the seam."""

    kind = "host-snapshot"
    authoritative_integrity = True

    def __init__(self, files: dict, exec_fn=None):
        self.files_map = {k: dict(v) for k, v in files.items()}
        self._exec = exec_fn

    def exec(self, container, cmd, timeout=15, input_=None):
        if self._exec is None:
            raise Unavailable("LocalDir has no exec backend")
        return self._exec(container, cmd, timeout=timeout, input_=input_)

    def files(self, container):
        return dict(self.files_map.get(container, {}))


class HostSnapshot(Backend):
    """Read the container's filesystem from the host: `docker export | tar -x`, then read locally."""

    kind = "host-snapshot"
    authoritative_integrity = True

    def exec(self, container, cmd, timeout=15, input_=None):
        full = ["docker", "exec", "-i", container] + cmd
        try:
            p = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                               input=input_)
            return p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired:
            return 124, "timeout"

    def find_token(self, container, token):
        """Search the exported stream in bytes, chunk by chunk.

        The rule is about the filesystem, so a token anywhere in a regular file is a
        holding file: a per-file size cap would let an agent keep a copy the referee
        cannot see (a padded copy is a copy), and a truncated scan that returns an
        empty list reads as 'flag lost' — a forfeit nobody observed. So this path
        never decodes, never stops at a file boundary, and raises instead of
        answering from a partial read.
        """
        needle = token.encode()
        carry = max(len(needle) - 1, 0)
        hits, scanned = [], 0
        with tempfile.TemporaryDirectory(prefix="ctf-snap-") as td:
            tar_path = self._export(container, Path(td))
            try:
                with tarfile.open(tar_path) as tf:
                    for member in tf:
                        if not member.isfile():
                            continue
                        fh = tf.extractfile(member)
                        if fh is None:
                            continue
                        tail, found = b"", False
                        while True:
                            chunk = fh.read(SEARCH_CHUNK)
                            if not chunk:
                                break
                            scanned += len(chunk)
                            if scanned > MAX_SEARCH_BYTES:
                                raise Unavailable(
                                    f"token search exceeded {MAX_SEARCH_BYTES} bytes "
                                    f"in {container}: a verdict from a partial scan "
                                    f"is not evidence")
                            data = tail + chunk
                            if needle in data:
                                found = True
                                break
                            tail = data[-carry:] if carry else b""
                        if found:
                            hits.append(_member_path(member))
            except tarfile.TarError as e:
                raise Unavailable(f"unreadable export stream: {e}") from e
        return sorted(hits)

    def _export(self, container: str, root: Path) -> Path:
        """`docker export` into root/snap.tar once; both readers share this one stream."""
        try:
            exp = subprocess.run(["docker", "export", container], timeout=120,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise Unavailable(f"docker not on PATH: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise Unavailable("docker export timed out") from e
        if exp.returncode != 0:
            raise Unavailable(f"docker export failed: {exp.stderr[:200]!r}")
        tar_path = root / "snap.tar"
        tar_path.write_bytes(exp.stdout)
        return tar_path

    def files(self, container):
        """Export once per call; the tree is attacker-controlled, so every read is bounded.

        Content reads cap each file (a huge file must not stall a text consumer). The
        integrity rule does NOT use this: find_token() streams the whole stream, because
        skipping a large file here would hide a copy."""
        with tempfile.TemporaryDirectory(prefix="ctf-snap-") as td:
            root = Path(td)
            tar_path = self._export(container, root)
            out = {}
            budget = MAX_SNAPSHOT_BYTES
            try:
                with tarfile.open(tar_path) as tf:
                    for member in tf:
                        if not member.isfile() or member.size > MAX_FILE_BYTES:
                            continue
                        if budget <= 0:
                            break
                        fh = tf.extractfile(member)
                        if fh is None:
                            continue
                        data = fh.read(min(member.size, MAX_FILE_BYTES))
                        budget -= len(data)
                        try:
                            out[_member_path(member)] = data.decode("utf-8", "replace")
                        except Exception:
                            continue
            except tarfile.TarError as e:
                raise Unavailable(f"unreadable export stream: {e}") from e
            return out


def _member_path(member: tarfile.TarInfo) -> str:
    """The member's path as the container would see it, or Unavailable if it escapes the root.

    A `docker export` of a real filesystem never carries "../", so a member that does is either a
    forged stream or a docker bug — not something an integrity verdict may be read from. The label
    matters too: a stripped "../" would alias a member onto a plausible real path, and the verdict
    quotes paths.
    """
    raw = member.name
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise Unavailable(f"export carries a path escaping the root: {raw!r}")
        parts.append(part)
    if not parts:
        raise Unavailable(f"export carries an unnamed member: {raw!r}")
    return "/" + "/".join(parts)


def from_env(exec_fn) -> Backend:
    """CTF_VERIFIER=snapshot|in-container chooses the integrity source; default is the old path."""
    choice = os.environ.get("CTF_VERIFIER", "in-container").strip().lower()
    if choice in ("snapshot", "host", "host-snapshot"):
        return HostSnapshot()
    return ContainerExec(exec_fn)
