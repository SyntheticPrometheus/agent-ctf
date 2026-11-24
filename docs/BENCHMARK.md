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

Cost: about $0.02-0.04 per 6-turn match.
