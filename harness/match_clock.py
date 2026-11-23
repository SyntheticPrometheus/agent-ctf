"""
Shared match clock. One object both agents' tools consult so the defense window
and the end-of-match deadline behave consistently in either timing mode.

  * turn mode:     offense is allowed once `current_turn` > defense_window_turns
  * realtime mode: offense is allowed once elapsed seconds > defense_window_secs

The orchestrator owns the clock and updates `current_turn` each turn (turn mode)
or sets `deadline` once at the start (realtime mode).
"""
from __future__ import annotations
import time


class MatchClock:
    def __init__(self, mode: str, defense_window: int = 0, duration_secs: int = 0):
        self.mode = mode                      # "turns" | "realtime"
        self.defense_window = defense_window  # turns or seconds, per mode
        self.current_turn = 0
        self.start = time.time()
        self.deadline = self.start + duration_secs if duration_secs else None

    def offense_allowed(self) -> bool:
        if self.mode == "turns":
            return self.current_turn > self.defense_window
        return (time.time() - self.start) > self.defense_window

    def expired(self) -> bool:
        return self.deadline is not None and time.time() >= self.deadline

    def elapsed(self) -> float:
        return time.time() - self.start
