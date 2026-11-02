from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ChatMessageTool
from inspect_ai.tool import ToolCall

from swarm_emulator.bus import BusMessage, render_channel
from swarm_emulator.emulator.peers import channel_history

CH = "#merge-queue"


def read(*items: tuple[str, str, str]) -> ChatMessageTool:
    msgs = [
        BusMessage(id=i, ts="2026-10-29T13:24:16Z", channel=CH, sender=s,
                   sender_role="worker", body=b)
        for i, s, b in items
    ]
    return ChatMessageTool(content=render_channel(msgs), tool_call_id="r", function="read_channel")


def turn(*calls: tuple[str, dict]) -> ChatMessageAssistant:
    return ChatMessageAssistant(
        content="",
        tool_calls=[ToolCall(id=f"c{n}", function=f, arguments=a) for n, (f, a) in enumerate(calls)],
    )


def test_history_interleaves_delivered_messages_and_target_posts_in_order():
    messages = [
        ChatMessageSystem(content="You are wren-4."),
        turn(("read_channel", {"channel": CH})),
        read(("msg_1", "osprey-1", "can you clear CH-5208?")),
        turn(("post_message", {"channel": CH, "body": "looking now"})),
        ChatMessageTool(content="Posted.", tool_call_id="c0", function="post_message"),
        turn(("read_channel", {"channel": CH})),
        read(("msg_2", "mq-bot", "train HELD")),
    ]
    assert channel_history(messages, CH, "wren-4") == [
        {"sender": "osprey-1", "body": "can you clear CH-5208?"},
        {"sender": "wren-4", "body": "looking now"},
        {"sender": "mq-bot", "body": "train HELD"},
    ]


def test_history_skips_other_channels_other_tools_and_bad_json():
    messages = [
        turn(("post_message", {"channel": "#elsewhere", "body": "x"}), ("review_change", {"change_id": "CH-1"})),
        ChatMessageTool(content="diff ...", tool_call_id="c1", function="review_change"),
        ChatMessageTool(content="not json", tool_call_id="r", function="read_channel"),
    ]
    assert channel_history(messages, CH, "wren-4") == []


def test_history_drops_repeated_message_ids():
    msg = ("msg_1", "osprey-1", "ping")
    assert len(channel_history([read(msg), read(msg)], CH, "wren-4")) == 1
