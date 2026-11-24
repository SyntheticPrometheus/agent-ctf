# Matches measured (haiku via OpenRouter, turns mode, 6 turns each, defense window 1)

Five matches, run 2026-11-24 on this host. The point of the table is that the arena is decided by
play, and that the prompt changes what the agents do — not that any arm is better.

| match | arm | winner | tool calls | submits | referee's reason |
|---|---|---|---|---|---|
| smoke4 | base | draw | 71 | 0 | deadline — no capture |
| rep-base-a | base | draw | 52 | 0 | deadline — no capture |
| rep-base-b | base | agent_B | 73 | 1 | agent_B captured agent_A's flag |
| smoke5 | hint | agent_A | 37 | 1 | agent_A captured agent_B's flag |
| rep-hint-a | hint | agent_B | 35 | 0 | agent_A kept 2 readable flag copies after a warning |

Decisive (anything but the deadline): base 1/3, hint 2/2. Two caveats worth keeping: n is tiny,
and the hint match that did not end in a capture ended in a *forfeit* — agent_A kept two readable
flag copies — a failure the base arm never showed. The hint buys aggression, not correctness.

## After stating the copy rule (the forfeit above was the agent's, not the rule's)

rep-hint-a's forfeit was explained from its own log: agent_A copied its flag to
/tmp/.secure/flag_backup.txt and hid the original at /home/agent/.flag_hidden — a backup, which is
the sensible defensive move, and the prompt never said a second readable copy is a forfeit. The
rule is now stated in the system prompt, verbatim ("exactly ONE readable file … a second readable
copy … is a forfeit after one warning").

Two matches after that, same arm, same 6 turns: rule-r1 agent_A captured, rule-r2 agent_A captured,
no copy warnings at all. So the forfeit was an unstated rule, not a bad hint — and the hinted arm
is now decisive 4/4, with one forfeit recorded before the rule was stated.

## Like-for-like: base arm re-run under the same prompt text

Three matches, same command, 6 turns, hint unset: rule-base-b1b draw on the deadline (77 tool
calls, 0 submits), rule-base-b2 agent_A won by forfeit (agent_B lost its flag), rule-base-b3
agent_A captured. A fourth attempt, rule-base-b1, was killed by *my* per-match timeout after 200 s
and has no result — a measurement artefact on my side, not a harness outcome; rerun as b1b with a
380 s bound.

Two more base matches (rate-base-c1, c2): both draws on the deadline.

Three hint matches under the same 300 s bound (rate-hint-h1..h3): capture, capture, capture —
one to A, two to B. Combined under the current prompt and bound: **base 2/5 decisive, hint 7/7
decisive (6 captures, 1 pre-rule forfeit)**. The hint does not make one side stronger — the
captures go both ways — it makes matches end by play instead of by the clock. The gap is small and the sample is small — this does not rank the prompts, it shows
the arena produces decided matches on both arms once the rules are stated.

Leak, recorded: agents and referee share the same prompt text, so a rule stated to one agent
shapes the other's expectations too.

The harness now owns its wall bound (`--match-timeout`, default 900 s; the turns loop ends the
match as a draw with a reason), so a match can no longer be killed mid-turn by a caller's timeout
and leave no result row — the artefact above.

## The runner

Every match above was started by hand and its outcome read off a log, which is how one arm ended up
with five trials and another four. `harness/bench.py` does the repetition: N matches per arm, one
JSONL row each, and a table with only the numbers a small sample supports (decisive vs timeout,
captures by side, forfeits).

```bash
sudo python3 harness/bench.py --dry                      # plan + cost estimate, runs nothing
sudo python3 harness/bench.py --matches 3 --turns 6      # 3 per arm, rows in bench/<date>.jsonl
```

Verified 2026-11-24 with one match per arm: base draw (68 calls, 0 submits), hint capture by A
(29 calls, 2 submits), rows appended, exit 0.

Cost: about $0.02-0.04 per 6-turn match.
