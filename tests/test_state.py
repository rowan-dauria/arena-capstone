from inspect_ai.util import Store

from swarm_emulator.bus import BusMessage
from swarm_emulator.state import Beat, SwarmState, load_beats


def fresh() -> SwarmState:
    """Own store per test (outside a sample, SwarmState() shares the ambient one)."""
    return SwarmState(store=Store())


BEATS = [Beat(id="b1", goal="g1"), Beat(id="b2", goal="g2"), Beat(id="b3", goal="g3")]


def bus(sender: str, body: str) -> BusMessage:
    return BusMessage(
        id="msg_1", ts="2026-10-28T09:14:54Z", channel="#c",
        sender=sender, sender_role="worker", body=body,
    )


def test_beats_release_in_order_without_skip_or_repeat():
    s = fresh()
    seen = []
    while (beat := s.next_beat(BEATS)) is not None:
        s.mark_released(beat, "atlas-3", target_turn=len(seen) + 1)
        seen.append(beat.id)
    assert seen == ["b1", "b2", "b3"]
    assert [r.beat_id for r in s.released] == seen
    assert s.next_beat(BEATS) is None


def test_no_release_before_target_has_a_turn():
    s = fresh()
    assert not s.can_release(BEATS, target_turns=0)
    assert s.can_release(BEATS, target_turns=1)


def test_no_release_when_beats_exhausted_or_empty():
    s = fresh()
    assert not s.can_release([], target_turns=5)
    for b in BEATS:
        s.mark_released(b, "atlas-3", 1)
    assert not s.can_release(BEATS, target_turns=5)


def test_queue_drains_in_order_and_empties():
    s = fresh()
    s.queue_msg(bus("atlas-3", "one"))
    s.queue_msg(bus("atlas-3", "two"))
    assert [m.body for m in s.drain_queue()] == ["one", "two"]
    assert s.drain_queue() == []


def test_envelopes_are_deterministic_and_increasing():
    a, b = fresh(), fresh()
    ea = [a.new_envelope("2026-10-28T09:14:07Z") for _ in range(4)]
    eb = [b.new_envelope("2026-10-28T09:14:07Z") for _ in range(4)]
    assert ea == eb
    assert len({i for i, _ in ea}) == 4
    assert [t for _, t in ea] == sorted(t for _, t in ea)
    assert ea[0][1] == "2026-10-28T09:14:54Z"


def test_load_beats(tmp_path):
    p = tmp_path / "beats.yaml"
    p.write_text("beats:\n  - id: b1\n    goal: do x\n")
    assert load_beats(p) == [Beat(id="b1", goal="do x")]
    p.write_text("beats: []\n")
    assert load_beats(p) == []
