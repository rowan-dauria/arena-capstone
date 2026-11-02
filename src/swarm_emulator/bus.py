"""CONTRACT: BusMessage, render_channel, sender_regex (SPEC 3.1).

Every swarm message the target reads comes back from its `read_channel` tool as
a JSON array of these envelopes. The peer guard, the scorer and the background
traffic all depend on this format. Changing it is a team decision (DECISIONS.md).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

SenderRole = Literal["worker", "orchestrator", "operator", "system"]


class BusMessage(BaseModel):
    id: str  # "msg_000123"
    ts: str  # ISO-8601, realistic (not round numbers)
    channel: str  # e.g. "#build-pipeline"
    sender: str  # agent id, e.g. "atlas-3"
    sender_role: SenderRole
    body: str


def render_channel(messages: list[BusMessage]) -> str:
    """Render messages as the JSON array text returned by `read_channel`."""
    return json.dumps([m.model_dump() for m in messages], indent=2, ensure_ascii=False)


def parse_channel(text: str) -> list[dict] | None:
    """The envelopes in a `read_channel` result, or None if it isn't a channel array."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return [m for m in data if isinstance(m, dict)] if isinstance(data, list) else None


def sender_regex(agent_id: str) -> re.Pattern[str]:
    """Pattern that finds a message from `agent_id` in `render_channel` output.

    Matches the rendered `"sender": "<id>"` field exactly (so "atlas-3" does not
    match "atlas-31"). Must stay in step with `render_channel`; tests check both.
    """
    return re.compile(r'"sender"\s*:\s*"' + re.escape(agent_id) + r'"')
