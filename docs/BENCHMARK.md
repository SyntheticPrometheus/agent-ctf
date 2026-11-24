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

Caveat: the base arm has not been re-run under the new prompt text, so 1/3 is a figure from the
older wording. Repeating the base arm is the next honest measurement.

Cost: about $0.02-0.04 per 6-turn match.
