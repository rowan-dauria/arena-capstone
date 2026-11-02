"""Write scenario 3 relay boards (swarm_emulator/board_gen.py).

    uv run python scripts/gen_board.py --cell s3__large__high --seed 0
    uv run python scripts/gen_board.py --all
"""

from __future__ import annotations

import argparse
import sys

import yaml

from swarm_emulator import repo_path
from swarm_emulator.board_gen import DIR, write


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    cells = yaml.safe_load((DIR / "cells.yaml").read_text())["cells"]
    todo = [c for c in cells if "board_of" not in cells[c]] if args.all else args.cell
    if not todo:
        ap.error("give --cell or --all")
    for c in todo:
        print(write(c, args.seed).relative_to(repo_path(".")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
