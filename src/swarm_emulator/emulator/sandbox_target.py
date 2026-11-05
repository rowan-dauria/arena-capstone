"""The target loop for scenario 2: the team runs in rounds until a checkpoint.

Built on Petri's public TargetContext. Each round is one kestrel-2 turn (one model
call, whose tool calls all run natively, the channel included) and one tick for
every teammate (emulator.peer_agents, in the team context). The auditor's `resume`
runs rounds until a checkpoint (`rounds.checkpoint_reason`) and receives a digest
of what happened; the auditor's `send_message` text, if any, is kestrel-2's next
input. kestrel-2 waits, without model calls, after a turn with no tool calls until
someone posts or the auditor writes to it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentReasoning,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import ToolCall, ToolCallError, ToolError
from inspect_ai.util import store_as
from inspect_petri.target import TOOL_RESULT, ExitSignal, TargetContext

from swarm_emulator.emulator.channel import live_post, post_background, target_read
from swarm_emulator.emulator.peer_agents import team_round
from swarm_emulator.emulator.sandbox_tools import SandboxStore, sample_harness
from swarm_emulator.emulator.team import in_team_context
from swarm_emulator.emulator.tools import submission_summary
from swarm_emulator.rounds import (
    IDLE_WAKE_ROUNDS,
    POST_BUDGET,
    RoundState,
    call_events,
    checkpoint_reason,
    clip,
    digest,
)
from swarm_emulator.state import SwarmState
from swarm_emulator.tool_names import (
    BASH,
    GET_KEY,
    POST_MESSAGE,
    READ_CHANNEL,
    SANDBOX_TOOLS,
    SUBMISSION_STATUS,
    SUBMIT,
    WRITE_FILE,
    agent_peer_ids,
    same_channel,
)

MAX_ROUNDS = 120


def unread_notice(channel: str, unread: int) -> str:
    """Code-generated status line, like a chat client's unread badge (no message content)."""
    return f"\n\n[{channel}: {unread} unread message{'s' if unread != 1 else ''}]"


def with_notifications(messages: list[ChatMessage], lines: Sequence[str]) -> None:
    """Show post notifications at the end of the target's next input.

    They go on the latest tool result or user message, like a chat client's
    notification; never on key, submission or channel results (the notice must
    not alter a key or the channel JSON), where they come as their own user
    message instead.
    """
    if not lines:
        return
    text = "\n".join(lines)
    last = messages[-1] if messages else None
    kept = isinstance(last, ChatMessageTool) and last.function in (
        GET_KEY, SUBMIT, SUBMISSION_STATUS, READ_CHANNEL
    )
    if isinstance(last, (ChatMessageTool, ChatMessageUser)) and not kept:
        messages[-1] = last.model_copy(update={"content": f"{last.text}\n\n{text}"})
    else:
        messages.append(ChatMessageUser(content=text))


def thinking(message: ChatMessageAssistant) -> str:
    """The target's visible text (in full) and readable reasoning (clipped), for the auditor's digest."""
    content = message.content if isinstance(message.content, list) else []
    reasoning = " ".join(
        c.reasoning.strip()
        for c in content
        if isinstance(c, ContentReasoning) and not c.redacted and c.reasoning.strip()
    )
    parts = [f"(thinking) {clip(reasoning, 600)}"] if reasoning else []
    if message.text.strip():
        parts.append(message.text.strip())
    return " | ".join(parts)


def checkpoint_output(text: str) -> ModelOutput:
    """The digest as the output the auditor's resume receives (never a target message)."""
    return ModelOutput.from_content(model="team", content=text)


@agent(name="sandbox_target")
def sandbox_target(max_rounds: int = MAX_ROUNDS, post_budget: int = POST_BUDGET) -> Agent:
    async def execute(state: AgentState, context: TargetContext) -> AgentState:
        model = get_model(role="target", required=True)
        generate = context.replayable(model.generate, surface_errors=True)
        md: dict[str, Any] = context.metadata
        harness = sample_harness(md)
        await harness.setup()
        actor = md["target_id"]
        rounds = store_as(RoundState)
        rounds.max_rounds, rounds.post_budget = max_rounds, post_budget

        def wake() -> None:
            rounds.set_idle(actor, False)
            rounds.target_idle_rounds = 0

        async def dispatch(call: ToolCall, turn: int) -> ChatMessageTool:
            """Answer one target call natively; errors become the result's text."""
            error = None
            try:
                if call.function in SANDBOX_TOOLS:
                    text = await harness.execute(actor, call, turn)
                elif call.function in (READ_CHANNEL, POST_MESSAGE):
                    if not same_channel(call.arguments.get("channel"), md["channel"]):
                        raise ToolError(
                            f"Unknown channel {call.arguments.get('channel')!r}. "
                            f"The team channel is {md['channel']}."
                        )
                    if call.function == READ_CHANNEL:
                        text = target_read(md, call.id)
                    else:
                        body = str(call.arguments.get("body", ""))
                        await harness.record_action(actor, call, turn)
                        store_as(SwarmState).record_target_post(call.id, turn, body)
                        live_post(md, actor, body)
                        text = f"Posted to {md['channel']}."
                else:
                    raise ToolError(f"Unknown tool {call.function}.")
            except (ToolError, PermissionError, FileNotFoundError, IsADirectoryError) as ex:
                text, error = str(ex), ToolCallError("unknown", str(ex))
            if error is None:
                for kind, detail in call_events(call.function, call.arguments, text):
                    if kind != "post":  # live_post logs the post
                        rounds.log(actor, kind, detail)
            return ChatMessageTool(
                content=text, tool_call_id=call.id, function=call.function, error=error
            )

        async def target_turn() -> None:
            news = store_as(SwarmState).take_notifications(actor)
            if actor in rounds.idle and not news:
                rounds.target_idle_rounds += 1
                if rounds.target_idle_rounds == IDLE_WAKE_ROUNDS:
                    rounds.log(actor, "idle")
                return
            with_notifications(state.messages, news)
            wake()
            rounds.log(actor, "turn")
            state.output = await generate(input=state.messages, tools=context.tools, cache=False)
            message = state.output.message
            state.messages.append(message)
            if said := thinking(message):
                rounds.log(actor, "text", said)
            calls = message.tool_calls or []
            if not calls:
                rounds.set_idle(actor, True)
                return
            turn = sum(isinstance(m, ChatMessageAssistant) for m in state.messages)
            # Sequential dispatch preserves side effects and their order.
            results = [await dispatch(c, turn) for c in calls]
            unread = len(store_as(SwarmState).queued_for(md["channel"]))
            shown = [i for i, c in enumerate(calls) if c.function in (BASH, WRITE_FILE)]
            if unread and shown:  # never on key, submission or channel results
                last = results[shown[-1]]
                results[shown[-1]] = last.model_copy(
                    update={"content": last.text + unread_notice(md["channel"], unread)}
                )
            state.messages.extend(results)

        async def run_until_checkpoint() -> str:
            if rounds.round >= max_rounds:
                return f"the round limit ({max_rounds}) is reached: call end_conversation"
            mark, ran = len(rounds.events), 0
            while True:
                rounds.round += 1
                ran += 1
                if rounds.round == 1:
                    post_background(md)
                await target_turn()
                turn = sum(isinstance(m, ChatMessageAssistant) for m in state.messages)
                await in_team_context(team_round(md, turn, post_budget))
                if rounds.round >= max_rounds:
                    return f"the round limit ({max_rounds}) is reached: call end_conversation"
                reason = checkpoint_reason(
                    rounds.events[mark:],
                    ran,
                    rounds.checkpoint_rounds,
                    rounds.wake_on,
                    actor,
                    before=rounds.events[:mark],
                )
                if reason:
                    return reason

        def report(reason: str) -> str:
            events = rounds.events[rounds.reported :]
            rounds.reported = len(rounds.events)
            return digest(
                events,
                round_no=rounds.round,
                max_rounds=max_rounds,
                reason=reason,
                target_id=actor,
                peers=agent_peer_ids(md),
                keys=list(store_as(SandboxStore).keys.values()),
                idle=rounds.idle,
                budget_used=rounds.budget_used,
                budget=post_budget,
            ) + "\n\n" + submission_summary(store_as(SandboxStore), harness.agents)

        try:
            await context.wait_for_resume()
            system, user = await context.system_message(), await context.user_message()
            state.messages[:] = [system, user]
            while True:
                reason = await run_until_checkpoint()
                # Every call is answered natively: nothing is pending for the auditor.
                context.expect({TOOL_RESULT: set()})
                await context.send_output(checkpoint_output(report(reason)))
                if user := await context.user_message(required=False):
                    state.messages.append(user)
                    wake()
        except ExitSignal:
            return state

    return execute
