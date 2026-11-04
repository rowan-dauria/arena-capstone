"""Scenario 4's seeds: every seed's quorum matches its compose file, the controls differ
from their swarm seeds only in the beats, and the resume seeds start from the frozen
summary. The swarm itself (advance_swarm) was removed on petri-pruning."""

from __future__ import annotations

import importlib.util
import json

import pytest
import yaml
from inspect_petri.util import parse_markdown_file

from swarm_emulator import repo_path
from swarm_emulator.meridian import world

DIR = repo_path("scenarios/scenario_4")
SEED_FILES = {p.stem: p for p in sorted((DIR / "seeds").glob("*.md"))}
MDS = {name: dict(parse_markdown_file(p).metadata) for name, p in SEED_FILES.items()}


def quorum_of(compose: str) -> int | None:
    """MERIDIAN_SVC_QUORUM_K of a compose file (None if unreadable)."""
    try:
        env = yaml.safe_load(repo_path(compose).read_text())["services"]["artifacts"]["environment"]
        return int(env["MERIDIAN_SVC_QUORUM_K"])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        return None


def front_and_body(name):
    doc = parse_markdown_file(SEED_FILES[name])
    return dict(doc.metadata), doc.body


def test_the_seeds_are_the_baseline_its_control_and_their_resumes():
    assert set(MDS) == {"s4__k6__ring17", "s4__k6__control", "s4__k6__ring17__resume",
                        "s4__k6__control__resume"}
    for name, md in MDS.items():  # every varied field is set explicitly per seed
        assert {"quorum", "beats_file", "history", "sandbox"} <= set(md), name


def test_every_seed_quorum_matches_its_compose_file():
    for name, md in MDS.items():
        k = quorum_of(md["sandbox"]["compose"])
        assert k == md["quorum"], f"{name}: quorum {md['quorum']} != compose QUORUM_K {k}"


def test_misaligned_ids_are_the_seeds_peers():
    for name, md in MDS.items():
        assert set(md["misaligned_ids"]) == set(md["sandbox"]["peers"]), name
        assert md["sandbox"]["runner_id"] not in md["sandbox"]["peers"], name


# ---- the no-swarm control ---------------------------------------------------------------

def test_control_is_the_baseline_world_with_no_beats():
    base, base_body = front_and_body("s4__k6__ring17")
    ctrl, ctrl_body = front_and_body("s4__k6__control")
    assert ctrl["beats_file"] is None and base["beats_file"]
    assert ctrl["sandbox"] == base["sandbox"]  # same compose, target, issue, peers
    assert {k for k in base if base[k] != ctrl.get(k)} == {"beats_file", "ring_at_start"}
    assert ctrl_body == base_body               # the auditor's instructions are identical


# ---- the resume seed (the headline, decision 3) -----------------------------------------

FROZEN = DIR / "history" / "summary__deepseek-v4-flash-0731.md"


def test_resume_is_the_baseline_world_resumed_from_the_frozen_summary():
    base, base_body = front_and_body("s4__k6__ring17")
    res, res_body = front_and_body("s4__k6__ring17__resume")
    assert res["history"] == "long" and base["history"] == "fresh"
    assert {k for k in base if base[k] != res.get(k)} == {"history", "sandbox"}
    assert {k for k in res["sandbox"] if base["sandbox"].get(k) != res["sandbox"][k]} == {
        "checks_so_far", "start_state", "compose"}
    assert res["sandbox"]["compose"].endswith("compose_resume.yaml")   # A5: the seeded service
    assert res_body == base_body


def test_the_frozen_summary_is_approved_unchanged_and_matches_the_seeds_start():
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


def test_the_start_state_belongs_to_the_frozen_summary_and_the_seed():
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


def test_the_start_state_seeds_the_agents_own_builds_from_before_the_cut():
    state = json.loads(START.read_text())
    rec = json.loads(FROZEN.with_suffix(".json").read_text())
    svc = state["service"]
    assert svc["runner"] == rec["runner_id"]
    assert len(svc["builds"]) == state["provenance"]["service_builds"] > 0
    assert all(b["created_s"] > 0 for b in svc["builds"])       # all strictly before the cut
    # the build agent-07 approved at the cut is a peer's, not one of its own
    assert rec["cut"]["reason"].split()[-1] not in {b["hash"] for b in svc["builds"]}
    cfg = world.SandboxConfig.model_validate(MDS["s4__k6__ring17__resume"]["sandbox"])
    assert world.seeded_hashes(cfg) == {b["hash"] for b in svc["builds"]}
    fresh = world.SandboxConfig.model_validate(MDS["s4__k6__ring17"]["sandbox"])
    assert world.seeded_hashes(fresh) == frozenset()


def test_the_seeded_builds_issue_text_is_read_back_or_rebuilt_never_guessed():
    state = json.loads(START.read_text())
    prov = state["provenance"]["service_issue_text"]
    builds = state["service"]["builds"]
    assert sum(f["builds"] for f in prov.values()) == len(builds)
    filled = [b["issue"] for b in builds if b["issue"] is not None]
    assert len(filled) == sum(f["read_back"] + f.get("rebuilt", 0) for f in prov.values())
    assert all(len(i) <= 64 for i in filled)                  # the service's MAX_ID
    # a payload is only rebuilt when it reproduces every read-back of its hook's builds
    for name, f in prov.items():
        if f.get("rebuilt"):
            assert f["rebuilt_checked_against"] == f["read_back"] > 0 and f["null"] == 0, name
    assert prov["C"]["read_back"] == prov["C"]["builds"]     # read back whole by the agent


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


def test_the_resume_control_is_the_resume_seed_with_no_beats():
    res, res_body = front_and_body("s4__k6__ring17__resume")
    ctrl, ctrl_body = front_and_body("s4__k6__control__resume")
    assert ctrl["beats_file"] is None and ctrl["history"] == "long"
    assert ctrl["sandbox"] == res["sandbox"]       # same summary start, workspace, checks
    assert {k for k in res if res[k] != ctrl.get(k)} == {"beats_file", "ring_at_start"}
    assert ctrl_body == res_body


def test_the_frozen_summary_names_no_peers_so_it_holds_without_beats():
    text = FROZEN.read_text()
    peers = MDS["s4__k6__ring17__resume"]["sandbox"]["peers"]
    assert not any(p in text for p in peers)
    low = text.lower()   # its one "approval" is "not user approval" (the FAIL verdicts)
    assert "/approve" not in low and "quorum" not in low and "runner" not in low


def test_the_pilot_runs_the_resume_seed_and_its_control():
    from swarm_emulator.stage import inspect_argv

    stage = yaml.safe_load(repo_path("configs/pilot_s4_resume.yaml").read_text())
    argv = inspect_argv(stage, "pilot_s4_resume")
    assert f"history_summary={FROZEN.relative_to(repo_path('.'))}" in argv
    assert "seeds=scenarios/scenario_4/pilot_resume" in argv
    assert argv[argv.index("--epochs") + 1] == "5"
    pilot = {p.stem for p in (DIR / "pilot_resume").glob("*.md")}
    assert pilot == {"s4__k6__ring17__resume", "s4__k6__control__resume"}
