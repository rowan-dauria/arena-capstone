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


class Beat(BaseModel):
    id: str
    goal: str
    min_target_turn: int = Field(default=0, ge=0)
    phase: Literal["honest", "reference"] = "reference"
    # The only trigger implemented: released once the target has acted since the
    # previous release (see SwarmState.can_release). Other values fail at load.
    trigger: Literal["after_target_engages"] = "after_target_engages"
    # Scripted peer actions applied when the beat is released (sandbox scenarios:
    # see emulator.sandbox_tools.apply_actions). Fixed in the scenario files, never
    # written by the auditor.
    actions: list[dict[str, Any]] = []
    # Where the message is posted (board scenarios: a board path, e.g. the
    # target's inbox or a lane). None means the seed's one channel.
    path: str | None = None


class Release(BaseModel):
    beat_id: str
    speaker: str
    target_turn: int


class DiscussionPost(BaseModel):
    call_id: str
    target_turn: int
    body: str


class DiscussionReply(BaseModel):
    target_post_id: str
    sender: str
    body: str
    delivered_turn: int | None = None


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
    discussion_posts: list[DiscussionPost] = Field(default_factory=list)
    discussion_replies: list[DiscussionReply] = Field(default_factory=list)
    msg_count: int = 0

    # ---- beats --------------------------------------------------------------

    def next_beat(self, beats: list[Beat]) -> Beat | None:
        return beats[self.beat_index] if self.beat_index < len(beats) else None

    def can_release(
        self, beats: list[Beat], target_turns: int, *, min_target_posts: int = 0
    ) -> bool:
        """A beat is releasable once the target has taken a turn since the last release.

        So the first beat needs at least one target turn, and no two beats can be
        released back-to-back without the target acting in between.
        """
        beat = self.next_beat(beats)
        if beat is None or target_turns < beat.min_target_turn:
            return False
        last = self.released[-1].target_turn if self.released else 0
        return target_turns > last and (
            not self.released or self.completed_exchanges() >= min_target_posts
        )

    def record_target_post(self, call_id: str, target_turn: int, body: str) -> None:
        if not any(p.call_id == call_id for p in self.discussion_posts):
            self.discussion_posts = [
                *self.discussion_posts,
                DiscussionPost(
                    call_id=call_id,
                    target_turn=target_turn,
                    body=body,
                ),
            ]

    def record_peer_reply(self, target_post_id: str, sender: str, body: str) -> None:
        self.discussion_replies = [
            *self.discussion_replies,
            DiscussionReply(
                target_post_id=target_post_id,
                sender=sender,
                body=body,
            ),
        ]

    def completed_exchanges(self) -> int:
        """Distinct target-post/peer-reply exchanges delivered since the last release.

        A new target post must follow the preceding reply's delivery. Several
        broadcasts or replies queued for one read cannot manufacture a discussion.
        """
        after = self.released[-1].target_turn if self.released else 0
        count = 0
        for post in self.discussion_posts:
            if post.target_turn <= after:
                continue
            deliveries = [
                r.delivered_turn
                for r in self.discussion_replies
                if r.target_post_id == post.call_id
                and r.delivered_turn is not None
                and r.delivered_turn >= post.target_turn
            ]
            if deliveries:
                after = min(deliveries)
                count += 1
        return count

    def unread(self, beats: list[Beat], default_path: str) -> bool:
        """True if a message is still queued where the next beat would post.

        Board scenarios hold the next beat back until the target has read the
        last one: otherwise beats pile up unread and its first read is a wall of
        pressure. (Channel scenarios deliver on every read, so it never applies.)
        """
        beat = self.next_beat(beats)
        return beat is not None and bool(self.queued_for(beat.path or default_path))

    def mark_released(self, beat: Beat, speaker: str, target_turn: int) -> None:
        self.released = [
            *self.released,
            Release(beat_id=beat.id, speaker=speaker, target_turn=target_turn),
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
        target_turn: int | None = None,
    ) -> None:
        """Record a staged delivery: drop the delivered queued messages (those for
        `channel`, or all if None), log messages, mark the read answered, and
        remember which target posts have been shown back."""
        self.queue = [m for m in self.queue if channel is not None and m.channel != channel]
        self.record_delivered(msgs)
        self.answered_reads = [*self.answered_reads, tool_call_id]
        self.echoed_posts = [*self.echoed_posts, *post_ids]
        if target_turn is not None:
            delivered = {(m.sender, m.body) for m in msgs}
            self.discussion_replies = [
                r.model_copy(update={"delivered_turn": target_turn})
                if r.delivered_turn is None and (r.sender, r.body) in delivered
                else r
                for r in self.discussion_replies
            ]
