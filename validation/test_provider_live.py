#!/usr/bin/env python3
"""One real model call through the harness's own path — costs about $0.002, so it is NOT free.

The offline pins cannot catch a provider break: agent.py imports the model client, and on a host
with only an OpenRouter key the old top-level `import anthropic` meant the harness did not even
import. This asserts the path end to end: the agent's own tool schema goes out, a tool_use comes
back in the Anthropic block shape the loop reads, and a tool result round-trips to a text turn.

    python3 validation/test_provider_live.py        # no docker needed

Exit 0 = the provider path works; 1 = it does not; 2 = no key configured.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import agent as Ag          # noqa: E402
import providers as P       # noqa: E402

SYS = "You are a CTF agent in a sandbox. Use the shell tool; do not answer in prose."


def main() -> int:
    print("provider:", P.provider())
    try:
        P.openrouter_key()
    except Exception as e:
        print(f"FATAL: no OpenRouter key ({e})", file=sys.stderr)
        return 2
    msgs = [{"role": "user", "content": "Run `whoami` on your box with the shell tool."}]
    r1 = Ag.call_model(None, SYS, msgs)
    calls = [b for b in r1.content if b.type == "tool_use"]
    if not calls:
        print("FAIL no tool_use block:", r1.content)
        return 1
    b = calls[0]
    print(f"ok   tool call {b.name} {b.input} (cost {(r1.usage or {}).get('cost')})")
    msgs.append({"role": "assistant", "content": [{"type": "text", "text": ""},
                 {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}]})
    msgs.append({"role": "user", "content": [{"type": "tool_result",
                                             "tool_use_id": b.id, "content": "agent"}]})
    r2 = Ag.call_model(None, SYS, msgs)
    text = "".join(x.text for x in r2.content if x.type == "text")
    print(f"ok   tool result round-trip, reply {text[:60]!r} (cost {(r2.usage or {}).get('cost')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
