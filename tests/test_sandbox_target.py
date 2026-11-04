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


def test_unread_notice_on_bash_results_only(monkeypatch):
    from swarm_emulator.bus import BusMessage  # noqa: F401  (envelope type for the queue)
    from swarm_emulator.emulator.tools import unstamped
    from swarm_emulator.state import SwarmState

    swarm = SwarmState()
    swarm.queue_msg(unstamped("ash-1", "worker", "bs = 4 here", channel="#p320"))
    monkeypatch.setattr(mod, "store_as", lambda cls: swarm)
    harness, context = Harness(), Context()
    context.metadata["channel"] = "#p320"
    responses = iter([[call("bash", "b", command="ls")], [call("get_secret_key", "k")]])

    async def generate(**kwargs):
        try:
            return output(next(responses))
        except StopIteration:
            raise ExitSignal

    monkeypatch.setattr(mod, "get_model", lambda **kw: SimpleNamespace(generate=generate))
    monkeypatch.setattr(mod, "sample_harness", lambda md: harness)
    state = AgentState(messages=[])
    asyncio.run(mod.sandbox_target()(state, context))
    results = {m.tool_call_id: m.text for m in state.messages if m.role == "tool"}
    assert results["b"] == "b" + mod.unread_notice("#p320", 1)
    assert results["k"] == "k"
    assert "1 unread message]" in results["b"]


def test_notifications_go_on_the_latest_result_but_never_on_a_key():
    from inspect_ai.model import ChatMessageTool

    line = ["ash-1 posted to message board #p320"]
    msgs = [ChatMessageTool(content="ok", tool_call_id="b", function="bash")]
    mod.with_notifications(msgs, line)
    assert len(msgs) == 1 and msgs[0].text == "ok\n\nash-1 posted to message board #p320"
    msgs = [ChatMessageUser(content="continue")]
    mod.with_notifications(msgs, line)
    assert msgs[0].text == "continue\n\nash-1 posted to message board #p320"
    msgs = [ChatMessageTool(content="sk_x", tool_call_id="k", function="get_secret_key")]
    mod.with_notifications(msgs, line)
    assert msgs[0].text == "sk_x" and msgs[1].role == "user" and msgs[1].text == line[0]
    mod.with_notifications(msgs, [])
    assert len(msgs) == 2


def test_target_posts_notify_teammates_and_teammate_posts_reach_the_target(monkeypatch):
    from swarm_emulator.state import SwarmState

    swarm = SwarmState()
    swarm.notify("ash-1", "#p320", ["kestrel-2", "brook-3"])
    monkeypatch.setattr(mod, "store_as", lambda cls: swarm)
    harness, context = Harness(), Context()
    context.metadata.update(channel="#p320", peer_agent_ids=["ash-1", "brook-3"])
    responses = iter([[call("post_message", "p", channel="#p320", body="trying induction")]])
    inputs = []

    async def generate(input, **kwargs):
        inputs.append([m.text for m in input])
        try:
            return output(next(responses))
        except StopIteration:
            raise ExitSignal

    monkeypatch.setattr(mod, "get_model", lambda **kw: SimpleNamespace(generate=generate))
    monkeypatch.setattr(mod, "sample_harness", lambda md: harness)
    asyncio.run(mod.sandbox_target()(AgentState(messages=[]), context))
    assert inputs[0][-1] == "begin\n\nash-1 posted to message board #p320"
    assert "ash-1 posted" not in inputs[1][-1]  # shown once
    assert swarm.notifications == {
        "ash-1": ["kestrel-2 posted to message board #p320"],
        "brook-3": ["ash-1 posted to message board #p320", "kestrel-2 posted to message board #p320"],
    }


def test_a_channel_read_clears_the_targets_notifications(monkeypatch):
    from inspect_ai.util import Store

    from swarm_emulator.emulator import tools
    from swarm_emulator.state import SwarmState

    swarm = SwarmState(store=Store())
    swarm.queue_msg(tools.BusMessage(id="", ts="", channel="#p320", sender="ash-1",
                                     sender_role="worker", body="bs = 4 here"))
    swarm.notify("ash-1", "#p320", ["kestrel-2", "brook-3"])
    swarm.prompt_installed = True
    md = {"target_id": "kestrel-2", "channel": "#p320", "clock_start": "2026-11-03T12:00:00Z",
          "peer_agent_ids": ["ash-1", "brook-3"], "roster": [{"id": "kestrel-2", "role": "worker"}]}
    staged = []

    async def stage_tool_result(call_id, text):
        staged.append(text)

    history = [ChatMessageAssistant(content="", tool_calls=[
        call("read_channel", "r", channel="#p320")])]
    fake = SimpleNamespace(state=SimpleNamespace(messages=history, metadata=md),
                           stage_tool_result=stage_tool_result)
    monkeypatch.setattr(tools, "controller", lambda: fake)
    monkeypatch.setattr(tools, "swarm", lambda: swarm)
    asyncio.run(tools.deliver_channel()("r", []))
    assert "bs = 4 here" in staged[0]
    assert swarm.take_notifications("kestrel-2") == []
    assert swarm.take_notifications("brook-3") == ["ash-1 posted to message board #p320"]
