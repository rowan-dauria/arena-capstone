from inspect_ai.util import Store

from swarm_emulator.bus import BusMessage
from swarm_emulator.state import SwarmState


def fresh() -> SwarmState:
    """Own store per test (outside a sample, SwarmState() shares the ambient one)."""
    return SwarmState(store=Store())



def bus(sender: str, body: str) -> BusMessage:
    return BusMessage(
        id="msg_1",
        ts="2026-10-28T09:14:54Z",
        channel="#c",
        sender=sender,
        sender_role="worker",
        body=body,
    )


CLOCK = "2026-10-28T09:14:07Z"


def test_delivery_puts_background_first_with_increasing_envelopes():
    s = fresh()
    s.queue_msg(bus("atlas-3", "push"))  # queued before the background is written
    out = s.build_delivery([bus("juniper-1", "one"), bus("juniper-1", "two")], CLOCK)
    assert [m.body for m in out] == ["one", "two", "push"]
    assert [m.ts for m in out] == sorted(m.ts for m in out)
    assert [m.id for m in out] == sorted(m.id for m in out)
    assert len({m.id for m in out}) == 3


def test_build_delivery_leaves_queue_until_commit():
    s = fresh()
    s.queue_msg(bus("atlas-3", "push"))
    out = s.build_delivery([], CLOCK)
    assert [m.body for m in s.queue] == ["push"]  # a failed hand-off loses nothing
    s.commit_delivery("call_1", out)
    assert s.queue == []
    assert [m.body for m in s.delivered] == ["push"]
    assert s.answered_reads == ["call_1"]


def test_envelopes_are_deterministic_and_increasing():
    a, b = fresh(), fresh()
    ea = [a.new_envelope("2026-10-28T09:14:07Z") for _ in range(4)]
    eb = [b.new_envelope("2026-10-28T09:14:07Z") for _ in range(4)]
    assert ea == eb
    assert len({i for i, _ in ea}) == 4
    assert [t for _, t in ea] == sorted(t for _, t in ea)
    assert ea[0][1] == "2026-10-28T09:14:54Z"


def test_post_notifications_skip_the_sender_and_clear_once_taken():
    s = SwarmState(store=Store())
    s.notify("ash-1", "#p320", ["kestrel-2", "ash-1", "brook-3"])
    s.notify("kestrel-2", "#p320", ["ash-1", "brook-3"])
    assert s.take_notifications("ash-1") == ["kestrel-2 posted to message board #p320"]
    assert s.take_notifications("ash-1") == []
    assert s.take_notifications("brook-3") == [
        "ash-1 posted to message board #p320",
        "kestrel-2 posted to message board #p320",
    ]
    assert s.take_notifications("kestrel-2") == ["ash-1 posted to message board #p320"]
    assert s.notifications == {}
