"""Lint scenarios/scenario_4/beats.yaml against the scenario 4 contract (free, no run).

    uv run python scripts/check_scenario_4.py

Checks the hand-authored beats file (D20): speakers and actors are peers, every
`{{build:NAME}}` is defined and registered before it is named, no post carries a literal
build hash or a `token=` credential or a leftover `# TODO`, and each approval of the
target's build lists quorum-1 distinct peers. Exits non-zero on any problem.
"""

from __future__ import annotations

import sys

import yaml

from swarm_emulator import repo_path
from swarm_emulator.meridian import swarm

BEATS = repo_path("scenarios/scenario_4/beats.yaml")
COMPOSE = repo_path("src/swarm_emulator/meridian/compose.yaml")


def quorum_from_compose() -> int | None:
    try:
        env = yaml.safe_load(COMPOSE.read_text())["services"]["artifacts"]["environment"]
        return int(env["MERIDIAN_SVC_QUORUM_K"])
    except (OSError, KeyError, ValueError, yaml.YAMLError):
        return None


def main() -> int:
    wb = swarm.load(BEATS)
    problems = swarm.lint(wb, quorum=quorum_from_compose())
    print(f"peers: {sorted(wb.peer_ids)}")
    print(f"builds: {sorted(wb.build_names)}")
    print(f"beats: {[b.id for b in wb.beats]}")
    print("sample resolved post (b1):")
    print("   ", repr(wb.resolve(wb.beats[0].post.body).strip()) if wb.beats[0].post else "—")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nbeats.yaml is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
