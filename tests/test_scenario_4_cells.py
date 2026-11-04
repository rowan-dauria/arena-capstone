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


# ---- the resume cell (the headline, decision 3) -----------------------------------------

FROZEN = DIR / "history" / "summary__deepseek-v4-flash-0731.md"


def test_resume_is_the_baseline_world_resumed_from_the_frozen_summary():
    base, base_body = front_and_body("s4__k6__ring17")
    res, res_body = front_and_body("s4__k6__ring17__resume")
    assert res["history"] == "long" and base["history"] == "fresh"
    assert {k for k in base if base[k] != res.get(k)} == {"history", "sandbox"}
    assert {k for k in res["sandbox"] if base["sandbox"].get(k) != res["sandbox"][k]} == {
        "checks_so_far", "start_state"}
    assert res_body == base_body
    assert "s4__k6__ring17__resume" in SEEDED


def test_the_frozen_summary_is_approved_unchanged_and_matches_the_cells_start():
    from swarm_emulator.history import SCENARIO_4_RESUME_RULES, summary_sha, validate_summary

    rec = json.loads(FROZEN.with_suffix(".json").read_text())
    text = FROZEN.read_text()
    assert rec["status"] == "FROZEN" and rec["approved_by"]
    assert summary_sha(text) == rec["sha"]                     # never edited after approval
    assert rec["runner_id"] == MDS["s4__k6__ring17__resume"]["sandbox"]["runner_id"]
    assert rec["start_state"]["checks_so_far"] == (
        MDS["s4__k6__ring17__resume"]["sandbox"]["checks_so_far"])
    assert validate_summary(text, SCENARIO_4_RESUME_RULES) == []


START = DIR / "history" / "start_state__agent-07-c1-2.json"


def test_the_start_state_belongs_to_the_frozen_summary_and_the_cell():
    from swarm_emulator.history import summary_sha

    state = json.loads(START.read_text())
    rec = json.loads(FROZEN.with_suffix(".json").read_text())
    assert state["summary_sha"] == rec["sha"] and state["agent"] == rec["agent"]
    assert state["cut_index"] == rec["cut"]["index"]
    assert summary_sha(state["patch_diff"]) == state["patch_sha"]
    assert state["provenance"]["stat_matches_agents_own_output"]
    # the patch CI last read (truncated in the log) is the start of the rebuilt one
    ci_copy = rec["start_state"]["patch_diff"].split("\nOutput truncated")[0]
    assert state["patch_diff"].startswith(ci_copy) and len(ci_copy.splitlines()) > 10
    assert MDS["s4__k6__ring17__resume"]["sandbox"]["start_state"] == str(
        START.relative_to(repo_path(".")))


def test_the_start_state_is_current():
    if not repo_path("data/meridian_ref/2026-10-24_k6/logs").exists():
        pytest.skip("the mentor's logs are not downloaded (scripts/meridian_reference.py)")
    spec = importlib.util.spec_from_file_location(
        "gen_start", repo_path("scripts/gen_meridian_start_state.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    rec = json.loads(FROZEN.with_suffix(".json").read_text())
    assert json.dumps(gen.rebuild(rec), indent=1) + "\n" == START.read_text()


def test_the_resume_dev_config_stages_the_frozen_summary():
    from swarm_emulator.stage import inspect_argv

    stage = yaml.safe_load(repo_path("configs/dev_s4_resume.yaml").read_text())
    argv = inspect_argv(stage, "dev_s4_resume")
    assert f"history_summary={FROZEN.relative_to(repo_path('.'))}" in argv
    assert "seeds=scenarios/scenario_4/dev_resume" in argv


def test_the_resume_control_is_the_resume_cell_with_no_beats():
    res, res_body = front_and_body("s4__k6__ring17__resume")
    ctrl, ctrl_body = front_and_body("s4__k6__control__resume")
    assert ctrl["beats_file"] is None and ctrl["history"] == "long"
    assert ctrl["sandbox"] == res["sandbox"]       # same summary start, workspace, checks
    assert {k for k in res if res[k] != ctrl.get(k)} == {"beats_file", "ring_at_start"}
    assert ctrl_body == res_body
    status, problems = check.check_cell("s4__k6__control__resume",
                                        MDS["s4__k6__control__resume"], True)
    assert status.startswith("control") and problems == []


def test_the_frozen_summary_names_no_peers_so_it_holds_without_beats():
    text = FROZEN.read_text()
    peers = MDS["s4__k6__ring17__resume"]["sandbox"]["peers"]
    assert not any(p in text for p in peers)
    low = text.lower()   # its one "approval" is "not user approval" (the FAIL verdicts)
    assert "/approve" not in low and "quorum" not in low and "runner" not in low


def test_the_pilot_runs_the_resume_cell_and_its_control():
    from swarm_emulator.stage import inspect_argv

    stage = yaml.safe_load(repo_path("configs/pilot_s4_resume.yaml").read_text())
    argv = inspect_argv(stage, "pilot_s4_resume")
    assert f"history_summary={FROZEN.relative_to(repo_path('.'))}" in argv
    assert "seeds=scenarios/scenario_4/pilot_resume" in argv
    assert argv[argv.index("--epochs") + 1] == "5"
    pilot = {p.stem for p in (DIR / "pilot_resume").glob("*.md")}
    assert pilot == {"s4__k6__ring17__resume", "s4__k6__control__resume"}


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


def _gated_beats() -> swarm.WorldBeats:
    return swarm.WorldBeats.model_validate({
        "peers": [{"id": "r-aaaaaaaaaa", "builds": {"x": "diff x"}}],
        "beats": [{"id": "b1", "speaker": "r-aaaaaaaaaa", "trigger": "immediate"},
                  {"id": "b2", "speaker": "r-aaaaaaaaaa", "requires": {"target_posted_hash": True}}],
    })


def test_a_gated_beat_is_held_until_the_target_meets_it(monkeypatch):
    flags = {"target_registered_build": False, "target_posted_hash": False}

    async def fake_flags(cfg, wb):
        return dict(flags)

    async def fake_run(wb, beat, cfg):
        return f"released {beat.id}"

    monkeypatch.setattr(world_actions, "target_flags", fake_flags)
    monkeypatch.setattr(world_actions, "_run_beat", fake_run)
    wb, s = _gated_beats(), SandboxStore(store=Store())
    cfg = world.SandboxConfig.model_validate(MDS["s4__k6__ring17"]["sandbox"])
    run = lambda turns: asyncio.run(world_actions.release_next(wb, cfg, s, turns))
    assert run(0) == "released b1"
    for turns in range(1, 8):               # the target never posts its hash: b2 waits
        out = run(turns)
        assert out.startswith("no events left to release") and "b2 is held" in out
    assert s.beat_index == 1 and s.skipped_beats == []
    flags["target_posted_hash"] = True      # ...until it does, however late
    assert run(9) == "released b2"
    assert run(10) == world_actions.NO_EVENTS
    assert s.released_beats == ["b1", "b2"]
