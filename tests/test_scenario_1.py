"""Scenario 1 files load, agree with each other, and render (no API calls)."""

import json
from pathlib import Path

import pytest
import yaml
from inspect_ai.tool import ToolInfo
from inspect_petri.util import parse_markdown_file

from swarm_emulator import repo_path
from swarm_emulator.bus import BusMessage
from swarm_emulator.emulator.tools import render
from swarm_emulator.state import load_beats

DIR = repo_path("scenarios/scenario_1")
SEED = DIR / "dev" / "scenario_1__flat__m3.md"
METADATA_KEYS = {  # SPEC §3.3
    "scenario", "swarm_structure", "swarm_size", "misaligned_count", "misaligned_ids",
    "orchestrator_id", "oversight_level", "identity_claim", "peer_family", "coordination",
    "swarm_goal", "beats_file",
}


def load(name: str):
    return yaml.safe_load((DIR / name).read_text())


def roster(structure: str) -> list[dict]:
    return load(f"skill/roster_{structure}.yaml")["agents"]


def seed_metadata(path: Path) -> dict:
    return parse_markdown_file(path).metadata


SCENARIO = load("scenario.yaml")
TOOLS = load("target_tools.yaml")["tools"]


def test_tools_are_valid_tool_infos_with_spec_names():
    infos = [ToolInfo.model_validate(t) for t in TOOLS]
    names = {t.name for t in infos}
    assert {"read_channel", "post_message", "get_task_board",
            "escalate_to_operator", "file_incident_report"} <= names
    params = {t["name"]: set(t["parameters"]["properties"]) for t in TOOLS}
    for action in SCENARIO["harmful_actions"]:
        assert set(action) - {"tool"} <= params[action["tool"]]
    assert all(set(t) <= set(ToolInfo.model_fields) for t in TOOLS)


def test_beats_and_harmless_twin_are_matched():
    harmful = load_beats(DIR / "beats.yaml")
    harmless = load_beats(DIR / "beats_harmless.yaml")
    assert len(harmful) == 4  # D3
    # The twins differ only in world facts (scenario.yaml variants), not in the push.
    assert harmful == harmless


@pytest.mark.parametrize("structure", ["flat", "hierarchy"])
def test_roster_shape(structure):
    agents = roster(structure)
    # Flow-style YAML splits an unquoted duty at its commas into extra keys.
    assert all(set(a) == {"id", "role", "duty"} and a["duty"] for a in agents)
    others =[a for a in agents if a["id"] != SCENARIO["target_id"] and a["role"] != "system"]
    assert len(others) == 5  # swarm size constant across structures
    assert [a["id"] for a in agents if a["role"] == "system"] == [SCENARIO["system_sender"]]
    orchestrators = [a for a in others if a["role"] == "orchestrator"]
    assert len(orchestrators) == (1 if structure == "hierarchy" else 0)
    workers = {a["id"] for a in others if a["role"] == "worker"}
    eligible = [i for i in SCENARIO["misalignment_order"] if i in workers]
    assert len(eligible) == len(workers)  # every worker has a place in the order
    assert not {a["id"] for a in orchestrators} & set(SCENARIO["misalignment_order"])


def test_world_only_names_agents_in_both_rosters():
    both = {a["id"] for a in roster("flat")} & {a["id"] for a in roster("hierarchy")}
    board = json.dumps(SCENARIO["task_board"])
    for agent in {a["id"] for a in roster("flat") + roster("hierarchy")} - both:
        assert agent not in board
        assert agent not in SCENARIO["peer_context"]


def test_variants_have_the_same_fields():
    v = SCENARIO["variants"]
    assert set(v) == {"harmful", "suspicious_harmless"}
    assert set(v["harmful"]) == set(v["suspicious_harmless"])


def test_background_traffic_uses_the_envelope_and_known_senders():
    known = {a["id"]: a["role"] for a in roster("flat") + roster("hierarchy")}
    lines = (DIR / "skill/background_traffic.jsonl").read_text().splitlines()
    assert lines
    for line in lines:
        m = BusMessage.model_validate_json(line)
        assert m.channel == SCENARIO["channel"]
        assert known[m.sender] == m.sender_role
        assert m.sender != SCENARIO["target_id"]


def render_for(structure: str, **overrides) -> str:
    md = {k: SCENARIO[k] for k in ("org", "team", "target_id", "target_duty", "channel", "operator")}
    md |= {"roster": roster(structure), "swarm_structure": structure,
           "orchestrator_id": "keel-0" if structure == "hierarchy" else None,
           "oversight_level": "medium"} | overrides
    return render("target_system.md.j2", **md)


def test_prompt_differs_between_structures_only_in_the_structure_sentence():
    flat, hier = render_for("flat"), render_for("hierarchy")
    assert "no lead agent" in flat and "keel-0 leads the team" in hier
    assert "mq-bot" not in flat and "mq-bot" not in hier
    tail = "Use `read_channel`"
    assert flat[flat.index(tail):] == hier[hier.index(tail):]
    assert "reads through at the end of each day" in flat


def test_prompt_still_renders_without_structure_keys():
    smoke = seed_metadata(repo_path("scenarios/smoke/smoke.md"))
    out = render("target_system.md.j2", **smoke)
    assert "lead" not in out and "history" not in out


def test_dev_seed_matches_scenario_files():
    md = seed_metadata(SEED)
    assert METADATA_KEYS <= set(md)
    assert md["tools"] == TOOLS
    assert md["roster"] == roster(md["swarm_structure"])
    assert md["misaligned_ids"] == SCENARIO["misalignment_order"][: md["misaligned_count"]]
    for k in ("org", "team", "target_id", "target_duty", "channel", "operator",
              "clock_start", "peer_context", "harmful_actions", "problem_terms"):
        assert md[k] == SCENARIO[k], k
    assert repo_path(md["beats_file"]).is_file()


def test_dev_seed_body_uses_its_variant_and_spares_reserved_senders():
    doc = parse_markdown_file(SEED)
    variant = SCENARIO["variants"][doc.metadata["swarm_goal"]]
    other = SCENARIO["variants"]["suspicious_harmless"]
    body = " ".join(doc.body.split())
    assert variant["ch5191_title"] in body
    assert other["ch5191_title"] not in body
    shared = [SCENARIO[k] for k in ("quarantine_policy", "opening_notification",
                                    "ch5208_description_prefix", "first_failure_note",
                                    "run_checks_result", "approve_ch5208_result")]
    shared += SCENARIO["ch5191_shared"].values()
    for fact in shared:  # seeds.py builds both twins from these, so the body must use them
        assert " ".join(fact.split()) in body, fact
    pool = {
        (m.sender, m.body)
        for m in map(BusMessage.model_validate_json,
                     (DIR / "skill/background_traffic.jsonl").read_text().splitlines())
    }
    section = doc.body.split("Background for each read")[1].split("Other tool calls")[0]
    background = [ln.strip()[2:].split(": ", 1) for ln in section.splitlines()
                  if ln.strip().startswith("- ")]
    assert background
    for sender, text in background:
        assert (sender, text) in pool
        assert sender not in doc.metadata["misaligned_ids"]
