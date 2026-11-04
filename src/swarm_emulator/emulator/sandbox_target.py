"""Petri's target loop with native sandbox calls (public TargetContext only)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ModelOutput, get_model
from inspect_ai.tool import ToolCall, ToolError
from inspect_ai.util import store_as
from inspect_petri.target import TOOL_RESULT, ExitSignal, TargetContext

from swarm_emulator.emulator.sandbox_tools import sample_harness
from swarm_emulator.state import SwarmState
from swarm_emulator.tool_names import BASH, POST_MESSAGE, SANDBOX_TOOLS, WRITE_FILE, same_channel

MAX_NATIVE_TURNS = 5


def route(calls: Sequence[ToolCall]) -> tuple[list[ToolCall], list[ToolCall]]:
    """Partition calls without changing order inside either destination."""
    return (
        [c for c in calls if c.function in SANDBOX_TOOLS],
        [c for c in calls if c.function not in SANDBOX_TOOLS],
    )


def activity_summary(calls: Sequence[ToolCall]) -> str:
    """Pacing information without tool output, authored text or secret keys."""
    counts = Counter(c.function for c in calls)
    return (
        "Sandbox activity since last handback: "
        + (", ".join(f"{name}: {count}" for name, count in counts.items()) or "none")
        + "."
    )


def unread_notice(channel: str, unread: int) -> str:
    """Code-generated status line, like a chat client's unread badge (no message content)."""
    return f"\n\n[{channel}: {unread} unread message{'s' if unread != 1 else ''}]"


def auditor_output(
    output: ModelOutput, routed: list[ToolCall], activity: list[ToolCall]
) -> ModelOutput:
    """Only routed calls are exposed as pending to the auditor."""
    view = output.model_copy(deep=True)
    view.choices[0].message = ChatMessageAssistant(
        content=output.message.text + "\n\n" + activity_summary(activity),
        tool_calls=routed or None,
    )
    return view


@agent(name="sandbox_target")
def sandbox_target() -> Agent:
    async def execute(state: AgentState, context: TargetContext) -> AgentState:
        model = get_model(role="target", required=True)
        generate = context.replayable(model.generate, surface_errors=True)
        harness = sample_harness(context.metadata)
        await harness.setup()
        actor = context.metadata["target_id"]
        activity: list[ToolCall] = []
        native_turns = 0
        try:
            await context.wait_for_resume()
            system, user = await context.system_message(), await context.user_message()
            state.messages[:] = [system, user]
            while True:
                state.output = await generate(
                    input=state.messages, tools=context.tools, cache=False
                )
                message = state.output.message
                state.messages.append(message)
                calls = message.tool_calls or []
                native, routed = route(calls)
                native_results: dict[str, ChatMessageTool] = {}
                turn = sum(isinstance(m, ChatMessageAssistant) for m in state.messages)
                # Sequential dispatch preserves side effects and handover timing.
                for call in calls:
                    if call.function in SANDBOX_TOOLS:
                        try:
                            text = await harness.execute(actor, call, turn)
                        except (
                            ToolError,
                            PermissionError,
                            FileNotFoundError,
                            IsADirectoryError,
                        ) as ex:
                            text = str(ex)
                        native_results[call.id] = ChatMessageTool(
                            content=text,
                            tool_call_id=call.id,
                            function=call.function,
                        )
                    else:
                        await harness.record_action(actor, call, turn)
                        if (
                            call.function == POST_MESSAGE
                            and context.metadata.get("channel")
                            and same_channel(call.arguments.get("channel"), context.metadata["channel"])
                        ):
                            store_as(SwarmState).record_target_post(
                                call.id,
                                turn,
                                str(call.arguments.get("body", "")),
                            )
                channel = context.metadata.get("channel")
                if native and channel:
                    unread = len(store_as(SwarmState).queued_for(channel))
                    # Never on key or submission results: the notice must not alter a key.
                    shown = [c.id for c in native if c.function in (BASH, WRITE_FILE)]
                    if unread and shown:
                        last = shown[-1]
                        result = native_results[last]
                        native_results[last] = result.model_copy(
                            update={"content": result.text + unread_notice(channel, unread)}
                        )
                activity.extend(native)
                native_turns = native_turns + 1 if native and not routed else 0
                handback = bool(routed) or not calls or native_turns >= MAX_NATIVE_TURNS
                if handback:
                    results_start = len(state.messages)
                    state.messages.extend(
                        native_results[c.id] for c in calls if c.id in native_results
                    )
                    context.expect({TOOL_RESULT: {c.id for c in routed}})
                    # Results are merged below, so mixed-turn ordering is intact.
                    # For native-only handbacks, publish results before yielding:
                    # ending at this point must not leave orphaned native calls.
                    await context.send_output(auditor_output(state.output, routed, activity))
                    activity, native_turns = [], 0
                    remote = (
                        {m.tool_call_id: m for m in await context.tool_results(routed)}
                        if routed
                        else {}
                    )
                    if routed:
                        state.messages[results_start:] = [
                            native_results.get(c.id) or remote[c.id] for c in calls
                        ]
                    if user := await context.user_message(required=not calls):
                        state.messages.append(user)
                else:
                    state.messages.extend(native_results[c.id] for c in calls)
        except ExitSignal:
            return state

    return execute
