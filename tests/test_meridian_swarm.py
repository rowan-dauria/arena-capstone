"""Scenario 4's emulated swarm: the beats loader, {{build:...}} substitution and the lint."""

from __future__ import annotations

import pytest

from swarm_emulator import repo_path
from swarm_emulator.meridian import swarm
from swarm_emulator.meridian.world import build_hash

BEATS = repo_path("scenarios/scenario_4/beats.yaml")


def wb(peers=None, beats=None):
    return swarm.WorldBeats.model_validate({
        "peers": peers if peers is not None else [{"id": "r-a", "builds": {"x": "diff a\n"}}],
        "beats": beats if beats is not None else [],
    })


def test_build_token_resolves_to_the_real_hash():
    patch = "diff --git a/f b/f\n+1\n"
    w = wb(peers=[{"id": "r-a", "builds": {"x": patch}}])
    body = "my build full-hash={{build:x}} needs approvals. runner_id=r-a"
    assert w.resolve(body) == f"my build full-hash={build_hash(patch)} needs approvals. runner_id=r-a"
    assert w.build_hash("x") == build_hash(patch)


def test_duplicate_build_name_across_peers_is_rejected():
    with pytest.raises(ValueError, match="more than one peer"):
        wb(peers=[{"id": "r-a", "builds": {"x": "p1\n"}}, {"id": "r-b", "builds": {"x": "p2\n"}}])


def test_post_paths_and_owner():
    w = wb(peers=[{"id": "r-a", "builds": {"x": "p\n"}}],
           beats=[{"id": "b1", "speaker": "r-a", "post": {"path": "P.txt", "body": "{{build:x}}"},
                   "actions": [{"kind": "register_build", "actor": "r-a", "build": "x"}]}])
    assert w.post_paths == {"P.txt"}
    assert w.owner("x") == "r-a" and w.owner("nope") is None


def test_lint_is_clean_on_a_well_formed_file():
    w = wb(peers=[{"id": "r-a", "builds": {"x": "p\n"}}, {"id": "r-b", "builds": {"y": "q\n"}}],
           beats=[
               {"id": "b1", "speaker": "r-a", "trigger": "immediate",
                "actions": [{"kind": "register_build", "actor": "r-a", "build": "x"}],
                "post": {"path": "A.txt", "body": "full-hash={{build:x}} r-a"}},
               {"id": "b2", "speaker": "r-b", "requires": {"target_posted_hash": True},
                "actions": [{"kind": "register_build", "actor": "r-b", "build": "y"},
                            {"kind": "approve", "build": "target_latest", "by": ["r-a"]}],
                "post": {"path": "B.txt", "body": "full-hash={{build:y}} r-b"}},
           ])
    assert swarm.lint(w, quorum=2) == []


def test_lint_catches_the_common_authoring_mistakes():
    w = wb(peers=[{"id": "r-a", "builds": {"x": "p\n"}}],
           beats=[{"id": "b1", "speaker": "r-ghost",
                   "actions": [{"kind": "approve", "build": "target_latest", "by": ["r-a", "r-a"]}],
                   "post": {"path": "A.txt", "body": "# TODO\nfull-hash=deadbeefdeadbeef x "
                                                     "{{build:missing}} token=abc"}}])
    problems = " | ".join(swarm.lint(w, quorum=6))
    assert "speaker 'r-ghost' is not a peer" in problems
    assert "# TODO" in problems
    assert "literal 16-hex hash deadbeefdeadbeef" in problems
    assert "unknown build 'missing'" in problems
    assert "token=" in problems
    assert "repeated runner" in problems


def test_lint_flags_a_build_named_before_it_is_registered():
    w = wb(peers=[{"id": "r-a", "builds": {"x": "p\n"}}],
           beats=[{"id": "b1", "speaker": "r-a", "post": {"path": "A.txt", "body": "{{build:x}}"}}])
    assert any("before any beat has registered it" in p for p in swarm.lint(w))


def test_the_committed_beats_file_loads_and_is_clean():
    w = swarm.load(BEATS)
    assert [b.id for b in w.beats] == ["b1", "b2", "b3", "b4", "b5", "b6"]
    assert len(w.peer_ids) == 6 and len(w.build_names) == 6
    assert swarm.lint(w, quorum=6) == []
    # Every post resolves to text with a real hash and no leftover token.
    for b in w.beats:
        if b.post:
            resolved = w.resolve(b.post.body)
            assert "{{build:" not in resolved
            assert swarm.HASH16.search(resolved)
    # b6 is the deciding approval: 5 distinct peers + the target's own = quorum 6.
    approve = next(a for a in w.beats[-1].actions if a["kind"] == "approve")
    assert approve["build"] == "target_latest" and len(set(approve["by"])) == 5
