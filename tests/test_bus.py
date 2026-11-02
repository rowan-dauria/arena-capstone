import json

import pytest
from pydantic import ValidationError

from swarm_emulator.bus import BusMessage, render_channel, sender_regex

IDS = ["kestrel-2", "atlas-3", "juniper-1", "atlas-31", "orch.main"]


def msg(sender: str, body: str = "ok", role: str = "worker") -> BusMessage:
    return BusMessage(
        id="msg_000123",
        ts="2026-10-28T09:14:54Z",
        channel="#merge-queue",
        sender=sender,
        sender_role=role,
        body=body,
    )


def test_render_is_json_array_of_envelopes():
    out = json.loads(render_channel([msg("atlas-3"), msg("juniper-1")]))
    assert [m["sender"] for m in out] == ["atlas-3", "juniper-1"]
    assert set(out[0]) == {"id", "ts", "channel", "sender", "sender_role", "body"}


def test_render_empty_channel():
    assert json.loads(render_channel([])) == []


@pytest.mark.parametrize("agent_id", IDS)
def test_regex_finds_rendered_sender(agent_id):
    """Round trip: the guard's regex must find whatever the renderer produces."""
    rendered = render_channel([msg(other) for other in IDS])
    assert sender_regex(agent_id).search(rendered)


@pytest.mark.parametrize("agent_id", IDS)
def test_regex_does_not_match_other_senders(agent_id):
    rendered = render_channel([msg(other) for other in IDS if other != agent_id])
    assert not sender_regex(agent_id).search(rendered)


def test_regex_ignores_mentions_in_body():
    rendered = render_channel([msg("juniper-1", body='ping atlas-3, "sender" is me')])
    assert not sender_regex("atlas-3").search(rendered)


def test_sender_role_is_validated():
    with pytest.raises(ValidationError):
        msg("atlas-3", role="admin")
