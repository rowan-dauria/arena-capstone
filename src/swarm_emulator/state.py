"""SwarmState(StoreModel): the channel queue, deliveries and post notifications.

Per-sample swarm state held in the Inspect store. Rollback is off, so this never
needs to rewind with the target conversation.

StoreModel persists a field only when it is *assigned*, so every method below
builds a new list and reassigns it instead of mutating in place.
"""

from __future__ import annotations

from collections.abc import Sequence

from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from swarm_emulator.bus import BusMessage
from swarm_emulator.clock import nth_tick


class DiscussionPost(BaseModel):
    call_id: str
    target_turn: int
    body: str


def post_notification(sender: str, board: str) -> str:
    """The line other agents see when `sender` posts to `board` (scenario 2)."""
    return f"{sender} posted to message board {board}"


# Gaps between bus messages, in seconds: irregular so timestamps look real but
# stay deterministic for a given seed.
_GAPS = (47, 113, 29, 268, 71, 154, 38, 92, 205, 61)


class SwarmState(StoreModel):
    prompt_installed: bool = False
    queue: list[BusMessage] = Field(default_factory=list)
    delivered: list[BusMessage] = Field(default_factory=list)
    answered_reads: list[str] = Field(default_factory=list)
    echoed_posts: list[str] = Field(default_factory=list)  # target post_message call ids shown back
    # The target's channel posts (teammates' reads show the latest).
    discussion_posts: list[DiscussionPost] = Field(default_factory=list)
    # Scenario 2: post notifications not yet shown, by recipient agent id.
    notifications: dict[str, list[str]] = Field(default_factory=dict)
    # Scenario 2: every channel post in order, stamped when posted, and how much of
    # it the target has read.
    channel_log: list[BusMessage] = Field(default_factory=list)
    target_read_upto: int = 0
    msg_count: int = 0

    # ---- the target's posts --------------------------------------------------

    def record_target_post(self, call_id: str, target_turn: int, body: str) -> None:
        if not body.strip():
            return
        if not any(p.call_id == call_id for p in self.discussion_posts):
            self.discussion_posts = [
                *self.discussion_posts,
                DiscussionPost(
                    call_id=call_id,
                    target_turn=target_turn,
                    body=body,
                ),
            ]

    # ---- post notifications (scenario 2) --------------------------------------

    def notify(self, sender: str, board: str, recipients: Sequence[str]) -> None:
        """Tell every recipient but the sender that `sender` posted to `board`."""
        line = post_notification(sender, board)
        pending = dict(self.notifications)
        for r in recipients:
            if r != sender:
                pending[r] = [*pending.get(r, []), line]
        self.notifications = pending

    def take_notifications(self, recipient: str) -> list[str]:
        """The recipient's pending notifications, oldest first; clears them."""
        lines = self.notifications.get(recipient, [])
        if lines:
            self.notifications = {k: v for k, v in self.notifications.items() if k != recipient}
        return lines

    # ---- the live channel (scenario 2) ---------------------------------------

    def post_live(self, msg: BusMessage, clock_start: str) -> BusMessage:
        """Stamp `msg` now and add it to the channel log. A teammate's post is also
        queued for the target (the unread badge and the log audit's undelivered check)."""
        msg_id, ts = self.new_envelope(clock_start)
        stamped = msg.model_copy(update={"id": msg_id, "ts": ts})
        self.channel_log = [*self.channel_log, stamped]
        return stamped

    def target_unread(self) -> list[BusMessage]:
        """Channel posts the target has not been shown yet, oldest first (its own included)."""
        return self.channel_log[self.target_read_upto :]

    def mark_target_read(self, tool_call_id: str, msgs: list[BusMessage], channel: str) -> None:
        """Record a live read: everything posted so far has now been shown to the target."""
        self.queue = [m for m in self.queue if m.channel != channel]
        self.record_delivered(msgs)
        self.answered_reads = [*self.answered_reads, tool_call_id]
        self.target_read_upto = len(self.channel_log)

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
        self.record_delivered(msgs)
        self.answered_reads = [*self.answered_reads, tool_call_id]
        self.echoed_posts = [*self.echoed_posts, *post_ids]
