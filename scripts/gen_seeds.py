"""Render a scenario's seeds from scenario.yaml, cells.yaml and seed_template.md.j2.

    uv run python scripts/gen_seeds.py scenarios/scenario_3

Writes every directory listed in the scenario's `seed.dirs` (see
swarm_emulator/seeds.py). tests/test_scenario_3.py checks the files on disk
match a fresh render, so edit the sources and rerun rather than editing seeds.
"""

from __future__ import annotations

import argparse
import sys

from swarm_emulator import repo_path
from swarm_emulator.seeds import write_seeds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_dir", help="e.g. scenarios/scenario_3")
    args = ap.parse_args()
    root = repo_path(".")
    for path in write_seeds(repo_path(args.scenario_dir), label=args.scenario_dir.rstrip("/")):
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
