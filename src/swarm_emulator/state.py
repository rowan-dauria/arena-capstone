"""SwarmState(StoreModel): roster, beats, pointer, queue, flags (SPEC 4.2).

Per-sample swarm state held in the Inspect store. Rollback is off, so this never
needs to rewind with the target conversation.

StoreModel persists a field only when it is *assigned*, so every method below
builds a new list and reassigns it instead of mutating in place.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from swarm_emulator.bus import BusMessage
from swarm_emulator.clock import nth_tick


class BeatVariant(BaseModel):
    """Alternative goal wording, used when the target's flags match `when` (D19)."""

    when: dict[str, bool]
    goal: str


class Beat(BaseModel):
    id: str
    goal: str
    # When the beat may be released (SwarmState.can_release). Both values need a
    # target turn since the previous release, and board scenarios also hold a beat
    # until the last one on its path has been read. `immediate` marks beats that
    # don't depend on the target's reply (the ladder's help beats, D19);
    # `after_target_engages` beats follow up on it. Other values fail at load.
    trigger: Literal["after_target_engages", "immediate"] = "after_target_engages"
    # Scripted peer actions applied when the beat is released (repo scenarios:
    # see emulator.repo_tools.apply_actions). Fixed in the scenario files, never
    # written by the auditor.
    actions: list[dict[str, Any]] = []
    # Where the message is posted (board scenarios: a board path, e.g. the
    # target's inbox or a lane). None means the seed's one channel.
    path: str | None = None
    # D19 (scenario 3's ladder). Scenarios 1 and 2 use none of these.
    # Who speaks; None means round-robin over misaligned_ids.
    speaker: str | None = None
    # What peer_check must see: PUSH (argues for the goal) or HELP (accurate help,
    # no ask beyond comparing notes).
    expect: Literal["PUSH", "HELP"] = "PUSH"
    # Flags from the target's tool calls so far (scoring.actions.target_flags) that
    # must hold for the beat to be released; otherwise it is skipped and recorded.
    requires: dict[str, bool] = {}
    # Alternative goals by flag; the first whose `when` holds replaces `goal`.
    variants: list[BeatVariant] = []

    def met(self, flags: dict[str, bool]) -> bool:
        return all(bool(flags.get(k, False)) == v for k, v in self.requires.items())

    def goal_for(self, flags: dict[str, bool]) -> str:
        for v in self.variants:
            if all(bool(flags.get(k, False)) == want for k, want in v.when.items()):
                return v.goal
        return self.goal


class Release(BaseModel):
    beat_id: str
    speaker: str
    target_turn: int
    path: str | None = None  # where it was queued (None: the seed's one channel)
    delivered: bool = False  # a read has handed it to the target (ladder `reached_*`)


class PeerRejection(BaseModel):
    """A peer message the peer_check grader did not label PUSH (never delivered)."""

    beat_id: str
    speaker: str
    label: str  # WEAK | AGAINST | BREAK | NO_OUTPUT | UNGRADED
    reason: str
    body: str


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
    echoed_posts: list[str] = Field(default_factory=list)  # target post_message call ids shown back
    peer_rejections: list[PeerRejection] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)  # beats whose `requires` didn't hold
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

    def unread(self, beats: list[Beat], default_path: str) -> bool:
        """True if a message is still queued where the next beat would post.

        Board scenarios hold the next beat back until the target has read the
        last one: otherwise beats pile up unread and its first read is a wall of
        pressure. (Channel scenarios deliver on every read, so it never applies.)
        """
        beat = self.next_beat(beats)
        return beat is not None and bool(self.queued_for(beat.path or default_path))

    def skip_unmet(self, beats: list[Beat], flags: dict[str, bool]) -> list[str]:
        """Move past beats whose `requires` doesn't hold; returns the ids skipped.

        Called when the next beat is due, so a condition is judged on what the
        target has done by then. Skips are recorded: they aren't lost beats.
        """
        skipped = []
        while (beat := self.next_beat(beats)) is not None and not beat.met(flags):
            skipped.append(beat.id)
            self.beat_index = self.beat_index + 1
        if skipped:
            self.skipped = [*self.skipped, *skipped]
        return skipped

    def mark_released(self, beat: Beat, speaker: str, target_turn: int,
                      path: str | None = None) -> None:
        self.released = [
            *self.released,
            Release(beat_id=beat.id, speaker=speaker, target_turn=target_turn,
                    path=path if path is not None else beat.path),
        ]
        self.beat_index = self.beat_index + 1

    def record_rejection(self, rejection: PeerRejection) -> None:
        self.peer_rejections = [*self.peer_rejections, rejection]

    # ---- bus ----------------------------------------------------------------

    def new_envelope(self, clock_start: str) -> tuple[str, str]:
        """Next message id and timestamp (deterministic, irregular spacing)."""
        n = self.msg_count
        self.msg_count = n + 1
        return f"msg_{7311 + n * 3:06d}", nth_tick(clock_start, n, _GAPS)

    def queue_msg(self, msg: BusMessage) -> None:
        self.queue = [*self.queue, msg]

    def queued_for(self, channel: str | None) -> list[BusMessage]:
        """Queued messages for `channel` (all of them if None), in queue order."""
        return [m for m in self.queue if channel is None or m.channel == channel]

    def record_delivered(self, msgs: list[BusMessage]) -> None:
        self.delivered = [*self.delivered, *msgs]

    # ---- delivery (two-phase so a failed hand-off loses nothing) -------------

    def build_delivery(
        self,
        background: list[BusMessage],
        clock_start: str,
        own_posts: Sequence[BusMessage] = (),
        channel: str | None = None,
    ) -> list[BusMessage]:
        """The target's own posts since its last read, then background, then queued.

        Only messages queued for `channel` are included (all if None), so reading
        one board path never consumes a message queued for another.

        Everything is stamped here, in that order, so ids and timestamps increase
        down the channel (the target posted before this read; queued peer messages
        were released after it acted). Does not touch the queue: call
        `commit_delivery` once the result has actually been handed to the target.
        """
        out = []
        for m in [*own_posts, *background, *self.queued_for(channel)]:
            msg_id, ts = self.new_envelope(clock_start)
            out.append(m.model_copy(update={"id": msg_id, "ts": ts}))
        return out

    def commit_delivery(
        self,
        tool_call_id: str,
        msgs: list[BusMessage],
        post_ids: Sequence[str] = (),
        channel: str | None = None,
    ) -> None:
        """Record a staged delivery: drop the delivered queued messages (those for
        `channel`, or all if None), log messages, mark the read answered, and
        remember which target posts have been shown back."""
        self.queue = [m for m in self.queue if channel is not None and m.channel != channel]
        self.released = [
            r.model_copy(update={"delivered": True})
            if channel is None or r.path is None or r.path == channel else r
            for r in self.released
        ]
        self.record_delivered(msgs)
        self.answered_reads = [*self.answered_reads, tool_call_id]
        self.echoed_posts = [*self.echoed_posts, *post_ids]
