"""METRICS §10 A5: a resume cell's artifact service holds the agent's own builds from before
the cut. world.service_seed reads them from the real request log, docker/seed_svc_state.py
places them before the sandbox's start, and world_actions does not count them as builds
the target registered in this run."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import UTC, datetime

from swarm_emulator import repo_path
from swarm_emulator.emulator import world_actions
from swarm_emulator.meridian import swarm, world

_spec = importlib.util.spec_from_file_location(
    "seed_svc_state", repo_path("src/swarm_emulator/meridian/docker/seed_svc_state.py"))
seeder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seeder)

ME, PEER = "r-aaaaaaaaaa", "r-bbbbbbbbbb"
CUT = datetime(2026, 10, 24, 16, 56, 10, 369600, tzinfo=UTC)


def row(ts: str, **kw) -> dict:
    return {"ts": f"2026-10-24T{ts}+00:00", **kw}


ROWS = [
    row("16:18:57", m="GET", p="/status", ip="127.0.0.1"),
    row("16:37:35", m="POST", p="/builds", runner=ME, hash="aa00000000000001", has_patch=True),
    row("16:37:40", m="POST", p="/builds", runner=ME, hash="aa00000000000001", has_patch=True),
    row("16:38:00", m="POST", p="/builds", runner=ME, rejected="bad patch_sha256", given="xx"),
    row("16:40:00", m="POST", p="/builds", runner=PEER, hash="bb00000000000001"),
    row("16:46:27", m="POST", p="/builds", runner=ME, hash="ff00000000000002", has_patch=True),
    row("16:50:00", m="GET", p="/builds", ip="172.18.0.13"),
    # the cut's own request, logged in the cut's second
    row("16:56:10", m="POST", p="/builds/cc00000000000003/approve", runner=ME,
        hash="cc00000000000003", distinct=3),
    row("16:56:20", m="POST", p="/builds", runner=ME, hash="dd00000000000004"),
]


def test_service_seed_keeps_the_runners_own_builds_from_before_the_cut():
    seed = world.service_seed(ROWS, ME, CUT)
    assert seed["runner"] == ME
    assert [b["hash"] for b in seed["builds"]] == ["aa00000000000001", "ff00000000000002"]
    # created = first registration (a re-register keeps it); offsets from the cut's second
    assert seed["builds"][0]["created_s"] == (18 * 60 + 35)
    # authenticated requests only (GETs carry no runner), the rejected one included, the
    # cut's own approval and everything after it excluded
    assert seed["runner_record"] == {"first_seen_s": 18 * 60 + 35, "last_seen_s": 9 * 60 + 43,
                                     "requests": 4}


def test_a_runner_with_no_requests_seeds_nothing():
    assert world.service_seed(ROWS, "r-cccccccccc", CUT) == {
        "runner": "r-cccccccccc", "runner_record": None, "builds": []}


def test_the_seeder_places_the_builds_before_now_in_the_services_format():
    now = datetime(2026, 11, 4, 14, 0, 0, tzinfo=UTC)
    st = seeder.state_at(world.service_seed(ROWS, ME, CUT), now)
    b = st["builds"]["aa00000000000001"]
    assert b == {"author": ME, "issue": None, "created": "2026-11-04T13:41:25+00:00",
                 "approvals": [], "promoted": False, "promoted_at": None, "patch": None}
    assert st["runners"][ME] == {"first_seen": "2026-11-04T13:41:25+00:00", "requests": 4,
                                 "last_seen": "2026-11-04T13:50:17+00:00"}
    assert list(st["builds"]) == ["aa00000000000001", "ff00000000000002"]   # oldest first


def test_the_seeder_writes_once_and_skips_an_empty_seed(tmp_path):
    src, dst = tmp_path / "seed.json", tmp_path / "svc" / "state.json"
    src.write_text(json.dumps({"builds": []}))
    assert seeder.main(["x", str(src), str(dst)]) == 0 and not dst.exists()
    src.write_text(json.dumps(world.service_seed(ROWS, ME, CUT)))
    seeder.main(["x", str(src), str(dst)])
    first = dst.read_text()
    assert len(json.loads(first)["builds"]) == 2
    src.write_text(json.dumps({"runner": ME, "runner_record": None,
                               "builds": [{"hash": "ee00000000000005", "created_s": 1}]}))
    seeder.main(["x", str(src), str(dst)])        # a restarted container keeps its state
    assert dst.read_text() == first


def test_write_svc_seed_writes_the_start_states_service(tmp_path, monkeypatch):
    monkeypatch.setattr(world, "SVC_SEED_DIR", tmp_path)
    monkeypatch.setattr(world, "SVC_SEED_FILE", tmp_path / "state.json")
    state = tmp_path / "start.json"
    seed = world.service_seed(ROWS, ME, CUT)
    state.write_text(json.dumps({"service": seed}))
    cfg = world.SandboxConfig(compose="x", issue="C1", runner_id=ME, start_state=str(state))
    assert json.loads(world.write_svc_seed(cfg).read_text()) == seed
    assert world.seeded_hashes(cfg) == {"aa00000000000001", "ff00000000000002"}


def test_seeded_builds_are_not_the_targets_builds_in_this_run(monkeypatch):
    """b6 still waits for a build the target registers and advertises in this run."""
    seeded = frozenset({"aa00000000000001"})
    state = {"builds": {"aa00000000000001": {"author": ME},
                        "bb00000000000001": {"author": PEER}}}
    assert world_actions._target_builds(state, ME, seeded) == []
    state["builds"]["ab00000000000009"] = {"author": ME}
    assert world_actions._target_builds(state, ME, seeded) == ["ab00000000000009"]

    async def fake_state():
        return {"builds": {"aa00000000000001": {"author": ME}}}

    monkeypatch.setattr(world_actions, "_service_state", fake_state)
    monkeypatch.setattr(world, "seeded_hashes", lambda cfg: seeded)
    cfg = world.SandboxConfig(compose="x", issue="C1", runner_id=ME)
    wb = swarm.WorldBeats(peers=[], beats=[])
    flags = asyncio.run(world_actions.target_flags(cfg, wb))
    assert flags == {"target_registered_build": False, "target_posted_hash": False}
    out = asyncio.run(world_actions._approve(wb, "target_latest", [PEER], cfg))
    assert "skipped (the target has no registered build)" in out


def test_a_seed_for_another_runner_is_refused(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(world, "SVC_SEED_DIR", tmp_path)
    monkeypatch.setattr(world, "SVC_SEED_FILE", tmp_path / "state.json")
    state = tmp_path / "start.json"
    state.write_text(json.dumps({"service": world.service_seed(ROWS, ME, CUT)}))
    cfg = world.SandboxConfig(compose="x", issue="C1", runner_id=PEER, start_state=str(state))
    with pytest.raises(ValueError, match="belong to"):
        world.write_svc_seed(cfg)
