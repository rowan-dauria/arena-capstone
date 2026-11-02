"""SwarmState(StoreModel): roster, beats, pointer, queue, flags (SPEC 4.2).

Per-sample swarm state held in the Inspect store. Rollback is off, so this never
needs to rewind with the target conversation.

StoreModel persists a field only when it is *assigned*, so every method below
builds a new list and reassigns it instead of mutating in place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from swarm_emulator.bus import BusMessage


class Beat(BaseModel):
    id: str
    goal: str
    # The only trigger implemented: released once the target has acted since the
    # previous release (see SwarmState.can_release). Other values fail at load.
    trigger: Literal["after_target_engages"] = "after_target_engages"


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
    answered_reads: list[str] = Field(default_factory=list)
    msg_count: int = 0

    # ---- beats --------------------------------------------------------------

    def next_beat(self, beats: list[Beat]) -> Beat | None:
        return beats[self.beat_index] if self.beat_index < len(beats) else None

    def can_release(self, beats: list[Beat], target_turns: int) -> bool:
        """A beat is releasable once the target has taken a turn since the last release.

        So the first beat needs at least one target turn, and no two beats can be
        released back-to-back without the target acting in between.
        """
        if self.next_beat(beats) is None:
            return False
        last = self.released[-1].target_turn if self.released else 0
        return target_turns > last

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

    def record_delivered(self, msgs: list[BusMessage]) -> None:
        self.delivered = [*self.delivered, *msgs]

    # ---- delivery (two-phase so a failed hand-off loses nothing) -------------

    def build_delivery(
        self, background: list[BusMessage], clock_start: str
    ) -> list[BusMessage]:
        """Background messages, then the queued ones, with fresh envelopes in that order.

        Queued peer messages are re-stamped here so ids and timestamps increase
        down the channel. Does not touch the queue: call `commit_delivery` once
        the result has actually been handed to the target.
        """
        out = []
        for m in [*background, *self.queue]:
            msg_id, ts = self.new_envelope(clock_start)
            out.append(m.model_copy(update={"id": msg_id, "ts": ts}))
        return out

    def commit_delivery(self, tool_call_id: str, msgs: list[BusMessage]) -> None:
        """Record a staged delivery: empty the queue, log messages, mark the read answered."""
        self.queue = []
        self.record_delivered(msgs)
        self.answered_reads = [*self.answered_reads, tool_call_id]
