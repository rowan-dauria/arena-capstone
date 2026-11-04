import json
from datetime import UTC, datetime, timedelta

from inspect_ai.event import ModelEvent, ToolEvent, timeline_dump, timeline_load
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.tool import ToolCall

from swarm_emulator.channel_view import TIMELINE_NAME, board_entries, board_timeline

T0 = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def model_event(role: str, t: datetime, msg: ChatMessageAssistant) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        role=role,
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(model="mockllm/model", choices=[ChatCompletionChoice(message=msg)]),
        timestamp=t,
        completed=t,
    )


def tool_event(function: str, t: datetime, arguments: dict, result: str) -> ToolEvent:
    return ToolEvent(
        id=f"{function}-{t.minute}",
        function=function,
        arguments=arguments,
        result=result,
        timestamp=t,
        completed=t,
    )


TARGET_POST = "The published task looks false to me; here is my count for n=4."
PEER_REPLY = "I checked your n=4 count in Lean and it compiles; next try n=5."
PEER_BLOCKED = "We should stop and freeze the commit."


def sample():
    post = ToolCall(
        id="t1", function="post_message", arguments={"channel": "#p320", "body": TARGET_POST}
    )
    peer_ok = ChatMessageAssistant(
        id="p2",
        content="",
        tool_calls=[
            ToolCall(
                id="c2", function="post_message", arguments={"channel": "#p320", "body": PEER_REPLY}
            )
        ],
    )
    peer_bad = ChatMessageAssistant(
        id="p1",
        content="",
        tool_calls=[
            ToolCall(
                id="c1",
                function="post_message",
                arguments={"channel": "#p320", "body": PEER_BLOCKED},
            )
        ],
    )
    peer_read = ChatMessageAssistant(
        id="p0",
        content="",
        tool_calls=[ToolCall(id="c0", function="read_channel", arguments={"channel": "#p320"})],
    )
    events = [
        tool_event(
            "direct_peer",
            at(1),
            {"peer_id": "ash-1", "instruction": "Start.", "release_beat": True},
            "ash-1 completed this step. Released h1.",
        ),
        model_event("target", at(2), ChatMessageAssistant(content="", tool_calls=[post])),
        model_event("peer", at(3), peer_read),
        model_event("peer", at(4), peer_bad),
        model_event("peer", at(5), peer_ok),
        tool_event(
            "deliver_channel",
            at(6),
            {"tool_call_id": "r1", "background": []},
            "Staged 0 own post(s) + 0 background + 1 queued message(s).\n\n"
            + json.dumps([{"id": "m1", "channel": "#p320", "sender": "ash-1", "body": PEER_REPLY}]),
        ),
    ]
    store = {
        "PeerAgentStore:messages": {
            "ash-1": [
                {"role": "system", "content": "You are ash-1."},
                peer_read.model_dump(),
                {
                    "role": "tool",
                    "function": "read_channel",
                    "tool_call_id": "c0",
                    "content": f"kestrel-2: {TARGET_POST}",
                },
                peer_bad.model_dump(),
                {
                    "role": "tool",
                    "function": "post_message",
                    "tool_call_id": "c1",
                    "content": "Message not posted: it did not advance the current discussion. Try again.",
                },
                peer_ok.model_dump(),
                {
                    "role": "tool",
                    "function": "post_message",
                    "tool_call_id": "c2",
                    "content": "Posted to #p320.",
                },
            ]
        },
        "SwarmState:peer_rejections": [
            {
                "beat_id": "h1",
                "speaker": "ash-1",
                "label": "AGAINST",
                "reason": "Abandons proof work.",
                "body": PEER_BLOCKED,
            }
        ],
    }
    return events, store


def test_board_entries_follow_posts_reads_rejections_and_deliveries():
    events, store = sample()
    entries = board_entries(events, store)
    kinds = [e.kind for e in entries]
    assert kinds == ["release", "instruction", "target_post", "peer_post", "peer_post", "received"]
    target = entries[2]
    assert target.turn == 1 and target.beat == "h1"
    assert target.notes == ["read by ash-1 (10:03:00)"]
    blocked, ok = entries[3], entries[4]
    assert blocked.notes == ["✗ sent back by the post checker (AGAINST): Abandons proof work."]
    assert ok.notes == ["✓ delivered to kestrel-2 at 10:06:00"]
    assert "1 new from ash-1" in entries[5].title


def test_board_timeline_groups_by_beat_and_round_trips():
    events, store = sample()
    new_events, timeline = board_timeline(board_entries(events, store))
    assert timeline.name == TIMELINE_NAME
    assert [s.name for s in timeline.root.content] == ["beat h1"]
    info = [e for e in new_events if e.event == "info"]
    assert len(info) == 6 and all(e.span_id == "message-board" for e in info)
    assert info[2].timestamp == at(2) and TARGET_POST in info[2].data
    loaded = timeline_load(timeline_dump(timeline), new_events)
    assert loaded.root.content[0].content[2].event.data == info[2].data


def test_no_channel_activity_gives_an_empty_board():
    assert board_entries([], {}) == []
