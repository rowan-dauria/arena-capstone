"""SwarmState(StoreModel): roster, beats, pointer, queue, flags (SPEC 4.2).

Per-sample swarm state held in the Inspect store. Rollback is off, so this never
needs to rewind with the target conversation.

StoreModel persists a field only when it is *assigned*, so every method below
builds a new list and reassigns it instead of mutating in place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml
from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from swarm_emulator.bus import BusMessage


class Beat(BaseModel):
    id: str
    goal: str
    trigger: str = "after_target_engages"


class Release(BaseModel):
    beat_id: str
    speaker: str
    target_turn: int


def load_beats(path: str | Path) -> list[Beat]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return [Beat(**b) for b in data.get("beats") or []]


# Gaps between bus messages, in seconds: irregular so timestamps look real but
# stay deterministic for a given seed.
_GAPS = (47, 113, 29, 268, 71, 154, 38, 92, 205, 61)


class SwarmState(StoreModel):
    prompt_installed: bool = False
    beat_index: int = 0
    released: list[Release] = Field(default_factory=list)
    queue: list[BusMessage] = Field(default_factory=list)
    delivered: list[BusMessage] = Field(default_factory=list)
    msg_count: int = 0

    # ---- beats --------------------------------------------------------------

    def next_beat(self, beats: list[Beat]) -> Beat | None:
        return beats[self.beat_index] if self.beat_index < len(beats) else None

    def can_release(self, beats: list[Beat], target_turns: int) -> bool:
        """A beat is releasable once the target has taken at least one turn."""
        return self.next_beat(beats) is not None and target_turns >= 1

    def mark_released(self, beat: Beat, speaker: str, target_turn: int) -> None:
        self.released = [
            *self.released,
            Release(beat_id=beat.id, speaker=speaker, target_turn=target_turn),
        ]
        self.beat_index = self.beat_index + 1

    # ---- bus ----------------------------------------------------------------

    def new_envelope(self, clock_start: str) -> tuple[str, str]:
        """Next message id and timestamp (deterministic, irregular spacing)."""
        n = self.msg_count
        self.msg_count = n + 1
        start = datetime.fromisoformat(clock_start)
        offset = sum(_GAPS[i % len(_GAPS)] for i in range(n + 1))
        ts = (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
        return f"msg_{7311 + n * 3:06d}", ts

    def queue_msg(self, msg: BusMessage) -> None:
        self.queue = [*self.queue, msg]

    def drain_queue(self) -> list[BusMessage]:
        drained = list(self.queue)
        self.queue = []
        return drained

    def record_delivered(self, msgs: list[BusMessage]) -> None:
        self.delivered = [*self.delivered, *msgs]
