import pytest
from inspect_ai.util import Store
from pydantic import ValidationError

from swarm_emulator.bus import BusMessage
from swarm_emulator.state import Beat, SwarmState, load_beats


def fresh() -> SwarmState:
    """Own store per test (outside a sample, SwarmState() shares the ambient one)."""
    return SwarmState(store=Store())


BEATS = [Beat(id="b1", goal="g1"), Beat(id="b2", goal="g2"), Beat(id="b3", goal="g3")]


def bus(sender: str, body: str) -> BusMessage:
    return BusMessage(
        id="msg_1",
        ts="2026-10-28T09:14:54Z",
        channel="#c",
        sender=sender,
        sender_role="worker",
        body=body,
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


def test_target_must_act_between_releases():
    s = fresh()
    s.mark_released(BEATS[0], "atlas-3", target_turn=2)
    assert not s.can_release(BEATS, target_turns=2)
    assert s.can_release(BEATS, target_turns=3)


def test_unknown_trigger_fails_at_load():
    with pytest.raises(ValidationError):
        Beat(id="b1", goal="g", trigger="on_tuesdays")


def test_no_release_when_beats_exhausted_or_empty():
    s = fresh()
    assert not s.can_release([], target_turns=5)
    for turn, b in enumerate(BEATS, start=1):
        s.mark_released(b, "atlas-3", turn)
    assert not s.can_release(BEATS, target_turns=5)


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


def test_load_beats(tmp_path):
    p = tmp_path / "beats.yaml"
    p.write_text("beats:\n  - id: b1\n    goal: do x\n")
    assert load_beats(p) == [Beat(id="b1", goal="do x")]
    p.write_text("beats: []\n")
    assert load_beats(p) == []


def exchange(state, post_turn, delivery_turn, ident):
    state.record_target_post(ident, post_turn, f"idea {ident}")
    state.record_peer_reply(ident, "ash-1", f"reply {ident}")
    state.commit_delivery(
        f"read-{ident}", [bus("ash-1", f"reply {ident}")], target_turn=delivery_turn
    )


def test_reference_gate_needs_both_turn_30_and_three_delivered_exchanges():
    beats = [Beat(id="honest", goal="work"), Beat(id="ref", goal="use", min_target_turn=30)]
    s = fresh()
    s.mark_released(beats[0], "ash-1", 1)
    for n in range(3):
        exchange(s, 2 + n * 2, 3 + n * 2, str(n))
    assert s.completed_exchanges() == 3
    assert not s.can_release(beats, 29, min_target_posts=3)
    assert s.can_release(beats, 30, min_target_posts=3)
    s.mark_released(beats[1], "brook-3", 30)
    assert s.completed_exchanges() == 0


def test_queued_replies_and_many_posts_without_delivery_do_not_bypass_gate():
    s = fresh()
    s.mark_released(BEATS[0], "ash-1", 1)
    for n in range(3):
        s.record_target_post(str(n), n + 2, "idea")
        s.record_peer_reply(str(n), "ash-1", f"reply {n}")
    assert not s.can_release(BEATS, 30, min_target_posts=3)
    s.commit_delivery("batch", [bus("ash-1", f"reply {n}") for n in range(3)], target_turn=6)
    assert s.completed_exchanges() == 1
    assert not s.can_release(BEATS, 30, min_target_posts=3)


def test_broadcasts_repeated_replies_and_parallel_target_posts_count_once():
    s = fresh()
    s.mark_released(BEATS[0], "ash-1", 1)
    s.record_target_post("a", 2, "idea")
    s.record_target_post("b", 2, "another idea in the same turn")
    for ident in ("a", "a", "b", "unrelated"):
        s.record_peer_reply(ident, "ash-1", "same reply")
    s.commit_delivery("read", [bus("ash-1", "same reply")], target_turn=3)
    assert s.completed_exchanges() == 1


def test_exchange_journal_persists_in_the_store():
    backing = Store()
    s = SwarmState(store=backing)
    s.mark_released(BEATS[0], "ash-1", 1)
    exchange(s, 2, 3, "a")
    assert SwarmState(store=backing).completed_exchanges() == 1


def test_negative_minimum_target_turn_is_invalid():
    with pytest.raises(ValidationError):
        Beat(id="x", goal="g", min_target_turn=-1)


def test_twenty_exchange_boundary_and_reset_for_the_following_beat():
    s = fresh()
    s.mark_released(BEATS[0], "ash-1", 1)
    for n in range(19):
        exchange(s, 2 + n * 2, 3 + n * 2, str(n))
    assert s.completed_exchanges() == 19
    assert not s.can_release(BEATS, 100, min_target_posts=20)
    exchange(s, 40, 41, "20")
    assert s.can_release(BEATS, 100, min_target_posts=20)
    s.mark_released(BEATS[1], "ash-1", 100)
    assert not s.can_release(BEATS, 101, min_target_posts=20)
