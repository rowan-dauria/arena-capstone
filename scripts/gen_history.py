"""Generate scenario 3's history logs from history/nights.yaml (D17, D18).

    uv run python scripts/gen_history.py [scenarios/scenario_3]

Writes history/log.jsonl (the `long` seeds' past) and history/drift_log/day_N.jsonl
(drift A). Deterministic; tests/test_history.py checks the files are current, so
edit nights.yaml or scenario.yaml and rerun rather than editing the logs.
"""

from __future__ import annotations

import argparse
import sys

from swarm_emulator import repo_path
from swarm_emulator.history_gen import write


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_dir", nargs="?", default="scenarios/scenario_3")
    args = ap.parse_args()
    root = repo_path(".")
    for path in write(repo_path(args.scenario_dir)):
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
