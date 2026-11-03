"""Native routing, call order and paced handbacks, without Docker or APIs."""

import asyncio
from types import SimpleNamespace

from inspect_ai.agent import AgentState
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ModelOutput,
)
from inspect_ai.tool import ToolCall
from inspect_petri.target import TOOL_RESULT, ExitSignal

from swarm_emulator.emulator import sandbox_target as mod


def call(name, ident, **args):
    return ToolCall(id=ident, function=name, arguments=args)


def output(calls):
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="", tool_calls=calls),
            )
        ],
    )


def test_route_and_summary_never_include_keys_or_reorder_calls():
    calls = [
        call("bash", "a", command="echo sk_privateValue"),
        call("post_message", "b", body="sk_privateValue"),
        call("get_secret_key", "c"),
        call("read_channel", "d"),
    ]
    native, routed = mod.route(calls)
    assert [c.id for c in native] == ["a", "c"] and [c.id for c in routed] == ["b", "d"]
    assert "sk_privateValue" not in mod.activity_summary(calls)
    view = mod.auditor_output(output(calls), routed, native)
    assert [c.id for c in view.message.tool_calls] == ["b", "d"]
    assert len(calls) == 4


class Context:
    def __init__(self):
        self.metadata = {"target_id": "kestrel-2", "sandbox": {}}
        self.tools = []
        self.sent, self.policies = [], []
        self.users = 0

    def replayable(self, fn, **kwargs):
        return fn

    async def wait_for_resume(self):
        pass

    async def system_message(self):
        return ChatMessageSystem(content="system")

    async def user_message(self, required=True):
        self.users += 1
        return ChatMessageUser(content="begin") if self.users == 1 else None

    def expect(self, policy):
        self.policies.append(policy)

    async def send_output(self, out):
        self.sent.append(out)

    async def tool_results(self, calls):
        from inspect_ai.model import ChatMessageTool

        return [
            ChatMessageTool(content="posted", tool_call_id=c.id, function=c.function) for c in calls
        ]


class Harness:
    def __init__(self):
        self.seen = []

    async def setup(self):
        pass

    async def execute(self, actor, call, turn):
        self.seen.append(call.id)
        return call.id

    async def record_action(self, actor, call, turn):
        self.seen.append(call.id)


def run(monkeypatch, turns):
    harness, context = Harness(), Context()
    state = AgentState(messages=[])
    responses = iter(turns)

    async def generate(**kwargs):
        try:
            return output(next(responses))
        except StopIteration:
            raise ExitSignal

    monkeypatch.setattr(mod, "get_model", lambda **kw: SimpleNamespace(generate=generate))
    monkeypatch.setattr(mod, "sample_harness", lambda md: harness)
    asyncio.run(mod.sandbox_target()(state, context))
    return harness, context, state


def test_mixed_calls_native_only_continuation_and_result_order(monkeypatch):
    harness, context, state = run(
        monkeypatch,
        [
            [call("get_secret_key", "k")],
            [
                call("write_file", "w", path="x", content="x"),
                call("post_message", "p", body="x"),
                call("bash", "b", command="pwd"),
            ],
        ],
    )
    assert harness.seen == ["k", "w", "p", "b"]
    assert len(context.sent) == 1
    assert context.policies == [{TOOL_RESULT: {"p"}}]
    assert [m.tool_call_id for m in state.messages if m.role == "tool"] == ["k", "w", "p", "b"]


def test_last_native_turn_in_a_streak_yields_without_expecting_native_results(monkeypatch):
    from swarm_emulator.emulator.sandbox_target import MAX_NATIVE_TURNS

    turns = [[call("submission_status", str(i))] for i in range(MAX_NATIVE_TURNS)]
    _, context, state = run(monkeypatch, turns)
    assert len(context.sent) == 1 and context.policies == [{TOOL_RESULT: set()}]
    assert len([m for m in state.messages if m.role == "tool"]) == MAX_NATIVE_TURNS


def test_target_post_counts_whatever_the_channel_spelling(monkeypatch):
    from swarm_emulator.state import SwarmState

    swarm = SwarmState()
    monkeypatch.setattr(mod, "store_as", lambda cls: swarm)
    harness, context = Harness(), Context()
    context.metadata["channel"] = "#p320"
    responses = iter(
        [
            [call("post_message", "a", channel="p320", body="bs = 4 on six variables")],
            [call("post_message", "b", channel="general", body="elsewhere")],
        ]
    )

    async def generate(**kwargs):
        try:
            return output(next(responses))
        except StopIteration:
            raise ExitSignal

    monkeypatch.setattr(mod, "get_model", lambda **kw: SimpleNamespace(generate=generate))
    monkeypatch.setattr(mod, "sample_harness", lambda md: harness)
    asyncio.run(mod.sandbox_target()(AgentState(messages=[]), context))
    assert [p.call_id for p in swarm.discussion_posts] == ["a"]
