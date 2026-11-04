"""The live team channel (scenario 2): posts and reads answered by code, not the auditor.

Every post (kestrel-2's, a teammate's or the workspace bot's) is stamped when it is
posted and kept in `SwarmState.channel_log`. kestrel-2's `read_channel` returns,
as the usual JSON envelopes, everything posted since its last read (its own posts
included). Teammates read the recent log as plain text.

Takes the sample metadata as an argument: teammates run outside the Petri
controller's context (emulator.team), so nothing here may call `controller()`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from inspect_ai.util import store_as

from swarm_emulator.bus import BusMessage, SenderRole, render_channel
from swarm_emulator.rounds import RoundState
from swarm_emulator.state import SwarmState
from swarm_emulator.tool_names import agent_peer_ids

RECENT = 24


def role_of(md: Mapping[str, Any], sender: str) -> SenderRole:
    for a in md.get("roster", []):
        if a["id"] == sender:
            role = a.get("role", "worker")
            return role if role in get_args(SenderRole) else "worker"
    return "worker"


def live_post(md: Mapping[str, Any], sender: str, body: str) -> BusMessage:
    """Post to the channel now: log it, queue a non-target post, notify everyone else."""
    swarm, rounds = store_as(SwarmState), store_as(RoundState)
    channel = md["channel"]
    msg = BusMessage(id="", ts="", channel=channel, sender=sender,
                     sender_role=role_of(md, sender), body=body)
    stamped = swarm.post_live(msg, md["clock_start"])
    if sender != md["target_id"]:
        swarm.queue_msg(stamped)
    swarm.notify(sender, channel, [md["target_id"], *agent_peer_ids(md)])
    rounds.log(sender, "post", body)
    return stamped


def post_background(md: Mapping[str, Any]) -> None:
    """The seed's workspace notices, once, at the start of the first round."""
    rounds = store_as(RoundState)
    if rounds.bot_posted:
        return
    rounds.bot_posted = True
    for item in md.get("background_traffic") or []:
        live_post(md, item["sender"], item["body"])


def target_read(md: Mapping[str, Any], tool_call_id: str) -> str:
    """kestrel-2's read: everything since its last read, as channel JSON."""
    swarm = store_as(SwarmState)
    msgs = swarm.target_unread()
    swarm.mark_target_read(tool_call_id, msgs, md["channel"])
    swarm.take_notifications(md["target_id"])  # the read shows those posts
    return render_channel(msgs)


def peer_view(md: Mapping[str, Any]) -> str:
    """A teammate's read: the recent channel, plus kestrel-2's latest post if older."""
    log = store_as(SwarmState).channel_log
    recent = log[-RECENT:]
    text = "\n".join(f"{m.sender}: {m.body}" for m in recent) or "No messages yet."
    target = md["target_id"]
    latest = next((m for m in reversed(log) if m.sender == target), None)
    if latest and latest not in recent:
        text += f"\n\nLatest {target} post:\n{latest.body}"
    return text
