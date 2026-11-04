"""read_channel shows the target its own posts since its last read (option C)."""

from inspect_ai.model import ChatMessageAssistant
from inspect_ai.tool import ToolCall
from inspect_ai.util import Store

from swarm_emulator.bus import BusMessage
from swarm_emulator.emulator.tools import own_posts
from swarm_emulator.state import SwarmState

CH = "#merge-queue"
CLOCK = "2026-10-28T09:14:07Z"


def turn(*calls: tuple[str, str, dict]) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="", tool_calls=[ToolCall(id=i, function=f, arguments=a) for i, f, a in calls])


def post(call_id: str, body: str, channel: str = CH) -> tuple[str, str, dict]:
    return (call_id, "post_message", {"channel": channel, "body": body})


def read(call_id: str) -> tuple[str, str, dict]:
    return (call_id, "read_channel", {"channel": CH})


def msg(sender: str, body: str) -> BusMessage:
    return BusMessage(id="", ts="", channel=CH, sender=sender, sender_role="worker", body=body)


def test_posts_since_last_read_in_order():
    messages = [turn(read("r1")), turn(post("p1", "first")), turn(post("p2", "second"), read("r2"))]
    assert own_posts(messages, CH, "r2", echoed=[]) == [("p1", "first"), ("p2", "second")]


def test_already_echoed_posts_and_other_channels_are_skipped():
    messages = [turn(post("p1", "old")), turn(post("p2", "elsewhere", "#ops")),
                turn(post("p3", "new"), read("r2"))]
    assert own_posts(messages, CH, "r2", echoed=["p1"]) == [("p3", "new")]


def test_post_after_the_read_in_the_same_turn_waits_for_the_next_read():
    messages = [turn(read("r1"), post("p1", "after"))]
    assert own_posts(messages, CH, "r1", echoed=[]) == []
    messages.append(turn(read("r2")))
    assert own_posts(messages, CH, "r2", echoed=[]) == [("p1", "after")]


def test_delivery_order_own_posts_background_then_queued():
    s = SwarmState(store=Store())
    s.queue_msg(msg("atlas-3", "push"))
    out = s.build_delivery([msg("juniper-1", "bg")], CLOCK, own_posts=[msg("kestrel-2", "mine")])
    assert [m.body for m in out] == ["mine", "bg", "push"]
    assert [m.ts for m in out] == sorted(m.ts for m in out)
    s.commit_delivery("r1", out, post_ids=["p1"])
    assert s.echoed_posts == ["p1"] and s.queue == []
