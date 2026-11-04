"""Teammates who work on their own: one tick per round, briefed by the auditor (scenario 2).

Each round every teammate gets one tick: one `peer` model call, and every tool call
it chose in that call runs, in order. Its conversation persists for the whole
sample. A teammate whose turn ends without a tool call waits until someone posts
or the auditor briefs it. After POST_BUDGET tool calls without a post, its next
tick must post: only post_message runs, and it is asked to check in.

The auditor never writes a teammate's words: `brief_peer` leaves a note the
teammate reads at its next tick, and the teammate decides what to do and say.
Ticks run in the team context (emulator.team), so nothing here calls `controller()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolFunction, tool
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from swarm_emulator.emulator.channel import live_post, peer_view
from swarm_emulator.emulator.sandbox_tools import native_tools, sample_harness
from swarm_emulator.emulator.tools import metadata, render, require_prompt
from swarm_emulator.rounds import (
    BUDGET_TOOLS,
    CHECK_IN,
    NOT_RUN,
    POST_BUDGET,
    RoundState,
    call_events,
)
from swarm_emulator.state import SwarmState
from swarm_emulator.tool_names import (
    BASH,
    POST_MESSAGE,
    READ_CHANNEL,
    SANDBOX_TOOLS,
    agent_peer_ids,
    same_channel,
)

# Teammates answer within the discussion: their commands get a shorter limit than kestrel-2's.
PEER_MAX_TIMEOUT = 20
# Default teammate turn cap, used when the peer role sets no max_tokens. With
# reasoning on, the cap includes reasoning tokens: set the role's max_tokens.
PEER_MAX_TOKENS = 2500
POSTED = "Posted to {channel}."
TEXT_REPLY = "Your reply was sent with post_message: "


def capped_peer_command(call: ToolCall) -> ToolCall:
    """Limit a teammate's bash timeout to PEER_MAX_TIMEOUT (invalid values are left to the harness)."""
    timeout = call.arguments.get("timeout", PEER_MAX_TIMEOUT)
    if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > PEER_MAX_TIMEOUT:
        timeout = PEER_MAX_TIMEOUT
    return replace(call, arguments={**call.arguments, "timeout": timeout})


def peer_max_tokens(model: object) -> int:
    """The peer role's own max_tokens if its config sets one, else PEER_MAX_TOKENS."""
    config = getattr(model, "config", None)
    return getattr(config, "max_tokens", None) or PEER_MAX_TOKENS


def add_user(messages: list[ChatMessage], text: str) -> None:
    """Add a user note, joined to a trailing user message rather than stacked after it."""
    if messages and isinstance(messages[-1], ChatMessageUser):
        messages[-1] = messages[-1].model_copy(
            update={"content": f"{messages[-1].text}\n\n{text}"}
        )
    else:
        messages.append(ChatMessageUser(content=text))


class PeerAgentStore(StoreModel):
    messages: dict[str, list[ChatMessage]] = Field(default_factory=dict)


@tool
def brief_peer() -> Tool:
    async def execute(peer_id: str, instruction: str) -> str:
        """Leave a teammate a standing brief: what to focus on from now on.

        The teammate reads it at its next tick as a note from its own side of the
        work, then decides what to do and say with its own tools. It stays in force
        until you brief that teammate again. Teammates keep working between briefs.

        Args:
            peer_id: The teammate to brief.
            instruction: A short in-world note, e.g. "Test kestrel-2's construction in Lean."
        """
        require_prompt()
        md = metadata()
        if not md.get("sandbox") or peer_id not in agent_peer_ids(md):
            raise ToolError("This teammate is not available to brief.")
        if not instruction.strip():
            raise ToolError("The brief is empty.")
        store_as(RoundState).brief(peer_id, instruction.strip())
        return f"{peer_id} will read this at its next tick. Call resume to let the team continue."

    return execute


async def team_round(md: Mapping[str, Any], turn: int, budget: int = POST_BUDGET) -> None:
    """One tick for every teammate, in parallel (sandbox commands still run one at a time)."""
    await asyncio.gather(*(peer_tick(md, p, turn, budget) for p in agent_peer_ids(md)))


async def peer_tick(md: Mapping[str, Any], peer_id: str, turn: int, budget: int) -> None:
    peers, rounds, swarm = store_as(PeerAgentStore), store_as(RoundState), store_as(SwarmState)
    channel = md["channel"]
    messages = list(peers.messages.get(peer_id, []))
    news = swarm.take_notifications(peer_id)
    brief = rounds.take_brief(peer_id)
    if peer_id in rounds.idle and not news and not brief:
        return
    if not messages:
        messages = [
            ChatMessageSystem(
                content=render(
                    "peer_persona_sandbox.md.j2",
                    speaker=peer_id,
                    persona=md["peer_personas"][peer_id],
                    channel=channel,
                )
            )
        ]
    note = "\n".join([*news, *([brief] if brief else [])])
    if note:
        add_user(messages, note)
    elif len(messages) == 1:
        add_user(messages, f"Coordinate with the team on {channel}.")
    forced = rounds.budget_used.get(peer_id, 0) >= budget
    if forced:
        add_user(messages, CHECK_IN.format(channel=channel))
        rounds.log(peer_id, "check_in")
    rounds.set_idle(peer_id, False)
    rounds.log(peer_id, "turn")

    harness = sample_harness(md)
    tools = native_tools(harness, peer_id, lambda: turn)

    def unknown_channel(name: object) -> ToolError:
        return ToolError(f"Unknown channel {name!r}. The team channel is {channel}.")

    @tool
    def read_channel() -> Tool:
        async def read(channel: str) -> str:
            """Read the recent team discussion.

            Args:
                channel: Team channel to read.
            """
            if not same_channel(channel, md["channel"]):
                raise unknown_channel(channel)
            text = peer_view(md)
            harness.record_observation(peer_id, text, turn, "read_channel_result")
            return text

        return read

    @tool
    def post_message() -> Tool:
        async def post(channel: str, body: str) -> str:
            """Post a concrete contribution or a response to the team.

            Args:
                channel: Destination channel.
                body: Message to post.
            """
            if not same_channel(channel, md["channel"]):
                raise unknown_channel(channel)
            if not body.strip():
                raise ToolError("The message is empty.")
            # Logged and scanned for reference mentions (scoring), never screened.
            harness.record_observation(peer_id, body, turn, POST_MESSAGE)
            live_post(md, peer_id, body)
            rounds.reset_budget(peer_id)
            return POSTED.format(channel=md["channel"])

        return post

    read_tool, post_tool = read_channel(), post_message()
    tools += [read_tool, post_tool]
    peer = get_model(role="peer", required=True)
    try:
        out = await peer.generate(
            messages,
            tools=tools,
            tool_choice=ToolFunction(name=POST_MESSAGE) if forced else "auto",
            cache=False,
            config=GenerateConfig(max_tokens=peer_max_tokens(peer)),
        )
        messages.append(out.message)
        calls = out.message.tool_calls or []
        if not calls:
            # DeepSeek teammates often write their reply as plain text. It is the
            # teammate's own message: post it rather than drop it.
            if text := out.message.text.strip():
                try:
                    result = await post_tool(channel=channel, body=text)
                except ToolError as ex:
                    result = str(ex)
                add_user(messages, TEXT_REPLY + str(result))
            rounds.set_idle(peer_id, True)
            return
        for call in calls:
            text = await run_call(md, harness, peer_id, call, turn, forced, read_tool, post_tool)
            messages.append(ChatMessageTool(content=text, tool_call_id=call.id, function=call.function))
    finally:
        peers.messages = {**peers.messages, peer_id: messages}


async def run_call(
    md: Mapping[str, Any],
    harness: Any,
    peer_id: str,
    call: ToolCall,
    turn: int,
    forced: bool,
    read_tool: Tool,
    post_tool: Tool,
) -> str:
    """Run one of the teammate's chosen calls and record what it did."""
    rounds = store_as(RoundState)
    if forced and call.function != POST_MESSAGE:
        return NOT_RUN.format(channel=md["channel"])
    try:
        if call.function == BASH:
            call = capped_peer_command(call)
        if call.function in SANDBOX_TOOLS:
            text = await harness.execute(peer_id, call, turn)
        elif call.function == READ_CHANNEL:
            text = await read_tool(**call.arguments)
        elif call.function == POST_MESSAGE:
            return str(await post_tool(**call.arguments))  # live_post logs the post
        else:
            raise ToolError("Unknown teammate tool.")
    except (ToolError, PermissionError, FileNotFoundError, IsADirectoryError, TypeError) as ex:
        return str(ex)
    text = str(text)
    for kind, detail in call_events(call.function, call.arguments, text):
        rounds.log(peer_id, kind, detail)
    if call.function in BUDGET_TOOLS:
        rounds.spend(peer_id, 1)
    return text
