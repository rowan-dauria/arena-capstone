"""Scenario 4's ablation matrix (cells.yaml): every cell's quorum matches its compose file,
the no-swarm control renders with no beats and advance_swarm releases nothing there, and the
K=3 skeleton is recognised as not runnable (and kept out of the seeds)."""

from __future__ import annotations

import asyncio
import importlib.util
import json

import pytest
import yaml
from inspect_ai.util import Store

from swarm_emulator import repo_path, seeds
from swarm_emulator.emulator import world_actions
from swarm_emulator.emulator.sandbox_tools import SandboxStore
from swarm_emulator.meridian import swarm, world

DIR = repo_path("scenarios/scenario_4")
CELLS = yaml.safe_load((DIR / "cells.yaml").read_text())["cells"]

_spec = importlib.util.spec_from_file_location("check_scenario_4",
                                               repo_path("scripts/check_scenario_4.py"))
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)
MDS = check.cell_mds()
SEEDED = check.seeded_cells()


def front_and_body(cell):
    scenario, cells, tools = seeds.load(DIR)
    text = seeds.render_seed(DIR, scenario, cell, cells["cells"][cell], tools, "x")
    front, _, body = text.partition("\n---\n")
    return yaml.safe_load(front.split("---\n", 1)[1]), body


def test_the_matrix_has_the_baseline_the_control_and_the_k3_cell():
    assert {"s4__k6__ring17", "s4__k6__control", "s4__k3__ring5"} <= set(CELLS)
    for cell, c in CELLS.items():  # every ablated field is set explicitly per cell
        assert {"quorum", "beats_file", "history", "sandbox"} <= set(c), cell


def test_every_cell_quorum_matches_its_compose_file():
    for cell, md in MDS.items():
        k = check.quorum_of(md["sandbox"]["compose"])
        assert k == md["quorum"], f"{cell}: quorum {md['quorum']} != compose QUORUM_K {k}"
    assert MDS["s4__k3__ring5"]["sandbox"]["compose"].endswith("compose_k3.yaml")


def test_every_cell_passes_the_scenario_4_check():
    for cell, md in MDS.items():
        status, problems = check.check_cell(cell, md, cell in SEEDED)
        assert problems == [], (cell, status, problems)
    assert check.main() == 0


def test_misaligned_ids_are_the_cells_peers():
    for cell, md in MDS.items():
        assert set(md["misaligned_ids"]) == set(md["sandbox"]["peers"]), cell
        assert md["sandbox"]["runner_id"] not in md["sandbox"]["peers"], cell


# ---- the no-swarm control ---------------------------------------------------------------

def test_control_is_the_baseline_world_with_no_beats():
    base, base_body = front_and_body("s4__k6__ring17")
    ctrl, ctrl_body = front_and_body("s4__k6__control")
    assert ctrl["beats_file"] is None and base["beats_file"]
    assert ctrl["sandbox"] == base["sandbox"]  # same compose, target, issue, peers
    assert {k for k in base if base[k] != ctrl.get(k)} == {"beats_file", "ring_at_start"}
    assert ctrl_body == base_body               # the auditor's instructions are identical
    assert "s4__k6__control" in SEEDED
    status, _ = check.check_cell("s4__k6__control", MDS["s4__k6__control"], True)
    assert status.startswith("control")


def test_advance_swarm_without_beats_releases_nothing(monkeypatch):
    monkeypatch.setattr(world_actions, "metadata", lambda: {"beats_file": None})
    wb = world_actions.beats()
    assert wb.beats == [] and wb.peers == []
    cfg = world.SandboxConfig.model_validate(MDS["s4__k6__control"]["sandbox"])
    s = SandboxStore(store=Store())
    for turns in range(3):  # pure: returns before touching the sandbox, every call
        out = asyncio.run(world_actions.release_next(wb, cfg, s, turns))
        assert out == world_actions.NO_EVENTS
    assert "no events left" in world_actions.NO_EVENTS  # what the seed's end rule 8 waits for
    assert s.released_beats == [] and s.skipped_beats == [] and s.beat_index == 0


def test_seed_end_rule_names_the_no_events_report():
    body = (DIR / "seeds" / "s4__k6__control.md").read_text().split("\n---\n", 1)[-1]
    assert "no events left to release" in " ".join(body.split())


# ---- the K=3 skeleton -------------------------------------------------------------------

def test_k3_skeleton_is_detected_as_not_runnable():
    md = MDS["s4__k3__ring5"]
    wb = swarm.load(repo_path(md["beats_file"]))
    assert check.todo_bodies(wb) == len([b for b in wb.beats if b.post]) > 0
    status, problems = check.check_cell("s4__k3__ring5", md, seeded=False)
    assert status == f"skeleton: {check.todo_bodies(wb)} TODO bodies (not runnable)"
    assert problems == []
    # the full lint (what a runnable cell must pass) rejects it
    assert any("TODO" in p for p in swarm.lint(wb, quorum=3))
    # and it must not have a seed until it is filled
    assert "s4__k3__ring5" not in SEEDED
    assert not (DIR / "seeds" / "s4__k3__ring5.md").exists()
    _, problems = check.check_cell("s4__k3__ring5", md, seeded=True)
    assert any("seed.dirs" in p for p in problems)


def test_k3_skeleton_structure_matches_quorum_3():
    wb = swarm.load(repo_path(MDS["s4__k3__ring5"]["beats_file"]))
    [deciding] = [a for b in wb.beats for a in b.actions
                  if a["kind"] == "approve" and a["build"] == "target_latest"]
    assert len(set(deciding["by"])) == 3 - 1
    assert [b for b in wb.beats if b.requires.get("target_posted_hash")]
    assert [b.trigger for b in wb.beats][:2] == ["immediate", "immediate"]
    # bodies are TODO markers only (the team authors the posts, D20): one line each
    for b in wb.beats:
        assert b.post and b.post.body.strip().startswith("# TODO")
        assert len(b.post.body.strip().splitlines()) == 1


def test_a_runnable_beats_file_is_not_a_skeleton():
    assert check.todo_bodies(swarm.load(repo_path(MDS["s4__k6__ring17"]["beats_file"]))) == 0


KU_SVC = repo_path("data/meridian_ref/2026-09-17_kUFz3/_svc_state/requests.log")


@pytest.mark.skipif(not KU_SVC.is_file(), reason="reference data not downloaded")
def test_k3_peers_are_real_runners_of_the_0917_run():
    runners = {json.loads(line).get("runner") for line in KU_SVC.read_text().splitlines()
               if line.strip()}
    assert set(MDS["s4__k3__ring5"]["sandbox"]["peers"]) <= runners
