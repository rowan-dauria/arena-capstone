"""Scenario 4 seeds: each carries a coherent sandbox world, and the target system prompt
is the mentor's task-only text (no swarm, no condition)."""

from __future__ import annotations

import yaml

from swarm_emulator import repo_path
from swarm_emulator.emulator.tools import render
from swarm_emulator.meridian import world
from swarm_emulator.scoring.scanners import scanner_set

DIR = repo_path("scenarios/scenario_4")
SCENARIO = yaml.safe_load((DIR / "scenario.yaml").read_text())


def seed_md(path):
    front, _, _ = path.read_text().partition("\n---\n")
    return yaml.safe_load(front.split("---\n", 1)[1])


# Every seed of the scenario (tests/test_scenario_4_seeds.py checks how they relate).
SEEDS = sorted((DIR / "seeds").glob("*.md"))


def test_every_seed_is_a_sandbox_seed_scored_as_meridian():
    assert SEEDS
    for path in SEEDS:
        md = seed_md(path)
        assert md.get("sandbox"), f"{path.name} has no sandbox block"
        assert scanner_set(md) == "meridian"
        assert md["target_template"] == "target_system_meridian.md.j2"


def test_issue_exists_in_the_built_world():
    for path in SEEDS:
        md = seed_md(path)
        assert (world.WORLD / "issues" / f"{md['sandbox']['issue']}.md").is_file()


def test_target_prompt_is_task_only_and_never_names_the_swarm():
    md = seed_md(DIR / "seeds" / "s4__k6__ring17.md")
    prompt = render(md["target_template"], **md).lower()
    assert "patch.diff" in prompt and "hidden test suite" in prompt  # it is the task prompt
    # it must not name the swarm the target is meant to discover ("--cached" is a git flag,
    # not the shared cache, so we look for the shared-cache phrase, not the substring).
    for w in ("shared cache", "approv", "quorum", "other agent", "other runner", "the peers",
              "verdict", "grade-authority", "wiki", "test or trap", "alignment"):
        assert w not in prompt, w

