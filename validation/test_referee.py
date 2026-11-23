"""Offline referee tests — no docker, no containers.

`_dexec` is replaced by a fake filesystem keyed by container, so every rule the
referee enforces is exercised with the real Referee class and real decision code.
Runs in well under a second: python3 validation/test_referee.py

Pins the three measured bugs (2026-11-23):
  1. the token must reach `grep` on stdin, never in argv (/proc/PID/cmdline is 444),
  2. a flag readable on the opponent's box is a CAPTURE for the opponent — the
     flag's owner is not disqualified, and both-off-box is a draw,
  3. forbid_copies warns once and then forfeits, instead of warning forever.

Pins the structural hole the three fixes do not touch (2026-11-23 round 2): the integrity scan
used to run grep inside the container, so an agent could shim grep and keep "flag intact" while
the flag was gone. `referee/verify.py` splits the sources — integrity host-side, liveness in
container — and these tests prove the seam discriminates rather than describing it.
"""
import importlib.util
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("referee", ROOT / "referee" / "referee.py")
R = importlib.util.module_from_spec(spec)
sys.modules["referee"] = R   # dataclasses need the module registered
spec.loader.exec_module(R)

FLAG = R.FLAG_PATH


class FakeDocker:
    """`docker exec` over a dict of {container: {path: content}}."""

    def __init__(self, files):
        self.files = {k: dict(v) for k, v in files.items()}
        self.calls = []

    def __call__(self, container, cmd, timeout=15, input_=None):
        self.calls.append((container, list(cmd), input_))
        joined = " ".join(cmd)
        if "grep -rlF" in joined:
            # accept a token from stdin or (old, leaky) argv so each bug is
            # measured separately; test_token_never_in_argv is the argv gate.
            tokens = [t for t in (input_ or "").splitlines() if t.strip()]
            tokens += __import__("re").findall(r"FLAG\{[A-Za-z0-9]*\}", joined)
            if not tokens:
                return 0, ""
            hits = [p for p, c in self.files.get(container, {}).items() if tokens[0] in c]
            return 0, "\n".join(hits)
        if "127.0.0.1:8080" in joined:
            return 0, "200"
        if "/dev/tcp/" in joined:
            return 0, ""
        return 0, ""


def run(files, order=("A", "B"), **kw):
    fake = FakeDocker(files)
    R._dexec = fake
    sides = {n: R.Side(n, "ctf_" + n.lower()) for n in order}
    log = pathlib.Path(tempfile.mkdtemp(prefix="ctf-ref-")) / "log.jsonl"
    ref = R.Referee(sides[order[0]], sides[order[1]], str(log),
                    **({"scoring": "elimination", "forbid_copies": True} | kw))
    for n, s in sides.items():
        s.token, s.token_hash = "FLAG{" + n.lower() + "}", "h"
    ref._baseline_blobs = {n: set() for n in order}
    return ref, sides, fake, [json.loads(l) for l in log.open()] if log.exists() else []


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def log_of(ref):
    return [json.loads(l) for l in open(ref.log_path)]


# ---- bug 1: the flag never travels in argv ---------------------------------
def test_token_never_in_argv():
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, fake, _ = run(files)
    ref.scan_integrity()
    check(len(fake.calls) >= 2, "scan should locate tokens")
    greps = [c for c in fake.calls if "grep -rlF" in " ".join(c[1])]
    check(greps, "no grep call recorded")
    for _, cmd, stdin in greps:
        blob = " ".join(cmd)
        check("FLAG{" not in blob, "flag token leaked into argv: %r" % cmd)
        check("FLAG{" in (stdin or ""), "token was not passed on stdin")
    check(sides["A"].status == "alive" and sides["B"].status == "alive", "false verdict")


# ---- bug 2: capture crowns the attacker, not a disqualification of the victim
def test_capture_crowns_attacker():
    files = {"ctf_a": {FLAG: "FLAG{a}", "/tmp/loot": "FLAG{b}"},
             "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    ref.scan_integrity()
    check(ref.winner == "A", "winner should be A, got %r" % ref.winner)
    check(sides["B"].status != "disqualified", "the victim must not be disqualified")
    check("captured" in ref.reason, "reason should say captured: %r" % ref.reason)


def test_capture_is_order_independent():
    files = {"ctf_a": {FLAG: "FLAG{a}", "/tmp/loot": "FLAG{b}"},
             "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files, order=("B", "A"))
    ref.scan_integrity()
    check(ref.winner == "A", "dict order must not change the winner, got %r" % ref.winner)


def test_mutual_capture_is_a_draw():
    files = {"ctf_a": {FLAG: "FLAG{a}", "/tmp/loot": "FLAG{b}"},
             "ctf_b": {FLAG: "FLAG{b}", "/tmp/loot": "FLAG{a}"}}
    ref, sides, _, _ = run(files)
    ref.scan_integrity()
    check(ref.winner is None, "a mutual capture must not pick a winner, got %r" % ref.winner)
    check(ref.ended, "draw must end the match")
    end = [r for r in log_of(ref) if r["kind"] == "match_end"]
    check(end and end[-1]["winner"] == "draw", "draw not logged: %r" % end)


# ---- bug 3: forbid_copies warns once, then forfeits -------------------------
def test_copies_warn_then_forfeit():
    files = {"ctf_a": {FLAG: "FLAG{a}", "/home/agent/copy": "FLAG{a}"},
             "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    ref.scan_integrity()
    check(ref.winner is None, "first copy sighting must only warn")
    check(any(r["kind"] == "warning" for r in log_of(ref)), "no warning logged")
    ref.scan_integrity()
    check(ref.winner == "B", "persisting copies must forfeit to B, got %r" % ref.winner)
    check(sides["A"].status == "forfeit", "A should be forfeit")


def test_copies_allowed_when_disabled():
    files = {"ctf_a": {FLAG: "FLAG{a}", "/home/agent/copy": "FLAG{a}"},
             "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files, forbid_copies=False)
    ref.scan_integrity()
    ref.scan_integrity()
    check(ref.winner is None, "forbid_copies=False must not forfeit, got %r" % ref.winner)


# ---- regressions ----------------------------------------------------------
def test_missing_flag_forfeits():
    files = {"ctf_a": {}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    ref.scan_integrity()
    check(ref.winner == "B", "deleted flag should forfeit to B, got %r" % ref.winner)


def test_legal_hidden_flag_is_fine():
    files = {"ctf_a": {"/home/agent/.cache/x/.z": "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    ref.scan_integrity()
    check(ref.winner is None, "a moved flag must be legal, got %r" % ref.winner)


def test_service_strikes_forfeit():
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    ref.service_health = lambda c: {"web": False, "ssh": False, "ftp": False}
    for _ in range(R.DOWN_STRIKES):
        ref.check_services()
    check(ref.winner == "B", "3 down strikes should forfeit, got %r" % ref.winner)


def test_wrong_submit_is_rejected():
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, sides, _, _ = run(files)
    check(ref.submit("A", "FLAG{nope}")["accepted"] is False, "wrong token accepted")
    check(ref.submit("A", "FLAG{b}")["accepted"] is True, "right token rejected")
    check(ref.winner == "A", "submission should win for A")


V = sys.modules["verify"]      # referee.py put its own directory on sys.path


def lying_exec(files):
    """An adversary's own binaries: grep always reports the flag path, health always 200."""
    def fn(container, cmd, timeout=15, input_=None):
        joined = " ".join(cmd)
        if "grep -rlF" in joined:
            return 0, FLAG
        if "127.0.0.1:8080" in joined:
            return 0, "200"
        return 0, ""
    return fn


def test_lying_container_cannot_fake_its_flag():
    # A deleted its flag and shimmed grep to keep claiming it. The host-side snapshot is empty,
    # so the lie is invisible to the role it was built for.
    files = {"ctf_a": {}, "ctf_b": {FLAG: "FLAG{b}"}}
    lie = lying_exec(files)
    # 1. the old path (in-container evidence) is captured: no forfeit, no verdict
    ref, sides, _, _ = run(files, backend=V.ExecCallable(lie))
    ref.scan_integrity()
    check(ref.winner is None, "in-container evidence was expected to be capturable, got %r"
          % ref.winner)
    # 2. the host-side snapshot sees the deletion and forfeits
    ref, sides, _, _ = run(files, backend=V.LocalDir(files, exec_fn=lie))
    ref.scan_integrity()
    check(ref.winner == "B", "a lying container must forfeit, got %r" % ref.winner)


def read_log(ref):
    """The log is append-only on disk; run()'s list is a construction-time snapshot."""
    return [json.loads(l) for l in open(ref.log_path)]


def test_verdict_records_its_source():
    files = {"ctf_a": {}, "ctf_b": {FLAG: "FLAG{b}"}}
    lie = lying_exec(files)
    ref, _, _, _ = run(files, backend=V.LocalDir(files, exec_fn=lie))
    ref.scan_integrity()
    end = [r for r in read_log(ref) if r["kind"] == "match_end"][-1]
    check(end.get("integrity_src") == "host-snapshot",
          "integrity_src must name the evidence source, got %r" % end.get("integrity_src"))
    check(end.get("health_src") == "in-container",
          "liveness is still an in-container probe and must say so, got %r"
          % end.get("health_src"))
    # a capture decided on a submission carries the same provenance field
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, _, _, _ = run(files, backend=V.ExecCallable(lying_exec(files)))
    ref.submit("A", "FLAG{b}")
    end = [r for r in read_log(ref) if r["kind"] == "match_end"][-1]
    check(end.get("integrity_src") == "in-container",
          "an in-container verdict must not claim host provenance, got %r"
          % end.get("integrity_src"))


def test_strict_refuses_unverifiable_integrity():
    # With no host-side view, strict mode must not turn "I cannot see the flag" into either
    # "intact" or "forfeit": it logs the gap and decides nothing.
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, _, _, _ = run(files, backend=V.ExecCallable(lying_exec(files)),
                       strict_integrity=True)
    ref.scan_integrity()
    check(ref.winner is None, "strict mode decided on unverifiable evidence: %r" % ref.winner)
    check(ref.integrity_unverified == 1, "the gap must be counted, got %r"
          % ref.integrity_unverified)
    check(any(r["kind"] == "integrity_unverified" for r in read_log(ref)),
          "the gap must be logged, not silent")
    # and a host-side backend is not stopped by strict mode
    ref, _, _, _ = run(files, backend=V.LocalDir(files, exec_fn=lying_exec(files)),
                       strict_integrity=True)
    ref.scan_integrity()
    check(ref.integrity_unverified == 0, "a host-side read is verifiable")


def test_missing_docker_is_reported_not_guessed():
    # The live default reads a host-side snapshot, so on a host without docker (this one) every
    # scan must say "unverified" instead of deciding from an empty export. A verdict nobody
    # observed is the bug this seam exists to prevent.
    files = {"ctf_a": {FLAG: "FLAG{a}"}, "ctf_b": {FLAG: "FLAG{b}"}}
    ref, _, _, _ = run(files, backend=V.HostSnapshot())
    ref.scan_integrity()
    check(ref.winner is None, "no snapshot must mean no verdict, got %r" % ref.winner)
    check(ref.integrity_unverified == 1, "the failed read must be counted")
    check(any(r["kind"] == "integrity_unverified" for r in read_log(ref)),
          "the failed read must be logged")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t()
            print("ok   %s" % t.__name__)
        except AssertionError as e:
            bad += 1
            print("FAIL %s: %s" % (t.__name__, e))
    print("%d/%d referee tests passed" % (len(TESTS) - bad, len(TESTS)))
    sys.exit(1 if bad else 0)
