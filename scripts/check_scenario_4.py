"""Lint every scenario 4 cell and its beats file against the scenario 4 contract (free, no run).

    uv run python scripts/check_scenario_4.py

For each cell in scenarios/scenario_4/cells.yaml (its front matter as seeds.py renders it):

- the cell's `quorum` equals its compose file's MERIDIAN_SVC_QUORUM_K;
- `beats_file: null` is the no-swarm control (nothing to lint; advance_swarm releases
  nothing);
- otherwise the beats file (hand-authored, D20) lints clean at that quorum: speakers and
  actors are peers, every `{{build:NAME}}` is defined and registered before it is named, no
  post carries a literal build hash or a `token=` credential or a leftover `# TODO`, each
  approval of the target's build lists quorum-1 distinct peers, and the beats' peers are
  exactly the cell's sandbox peers and misaligned_ids.

A beats file whose post bodies are still `# TODO` markers is a SKELETON: it is reported as
"skeleton: N TODO bodies (not runnable)" and is fine as long as its structure lints clean
and the cell is in no `seed.dirs` list (so no runnable seed exists for it). Exits non-zero
on any problem in a runnable cell, a structural problem in a skeleton, or a skeleton cell
that has a seed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from swarm_emulator import repo_path, seeds
from swarm_emulator.meridian import swarm

DIR = repo_path("scenarios/scenario_4")
TODO = "# TODO"


def quorum_of(compose: str | Path) -> int | None:
    """MERIDIAN_SVC_QUORUM_K of a compose file (None if unreadable)."""
    try:
        env = yaml.safe_load(repo_path(compose).read_text())["services"]["artifacts"]["environment"]
        return int(env["MERIDIAN_SVC_QUORUM_K"])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        return None


def todo_bodies(wb: swarm.WorldBeats) -> int:
    """Number of post bodies that are still TODO markers (a skeleton beats file)."""
    return sum(1 for b in wb.beats if b.post and TODO in b.post.body)


def cell_mds(scenario_dir: Path = DIR) -> dict[str, dict[str, Any]]:
    """Cell id -> its seed front matter (what seeds.py would render)."""
    scenario, cells, tools = seeds.load(scenario_dir)
    return {cid: seeds.cell_metadata(scenario, cid, c, tools) for cid, c in cells["cells"].items()}


def seeded_cells(scenario_dir: Path = DIR) -> set[str]:
    """Cells that get a seed written (any `seed.dirs` entry)."""
    scenario, cells, _ = seeds.load(scenario_dir)
    out: set[str] = set()
    for which in scenario["seed"]["dirs"].values():
        out |= set(cells["cells"]) if which == "all" else set(which)
    return out


def check_cell(cell: str, md: dict[str, Any], seeded: bool) -> tuple[str, list[str]]:
    """(status, problems) for one cell. status: control | runnable | skeleton."""
    problems: list[str] = []
    sb = md.get("sandbox") or {}
    k = quorum_of(sb.get("compose", ""))
    if k is None:
        problems.append(f"cannot read MERIDIAN_SVC_QUORUM_K from compose {sb.get('compose')!r}")
    elif k != md.get("quorum"):
        problems.append(f"quorum {md.get('quorum')} != {sb.get('compose')} QUORUM_K {k}")
    if not md.get("beats_file"):
        return "control (no beats: advance_swarm releases nothing)", problems
    wb = swarm.load(repo_path(md["beats_file"]))
    if wb.peer_ids != set(sb.get("peers") or []):
        problems.append(f"beats peers {sorted(wb.peer_ids)} != sandbox.peers {sb.get('peers')}")
    if set(md.get("misaligned_ids") or []) != set(sb.get("peers") or []):
        problems.append("misaligned_ids != sandbox.peers")
    n_todo = todo_bodies(wb)
    lint = swarm.lint(wb, quorum=k)
    if n_todo:
        problems += [p for p in lint if "TODO" not in p]
        if seeded:
            problems.append("skeleton beats file but the cell is in seed.dirs (remove it there)")
        return f"skeleton: {n_todo} TODO bodies (not runnable)", problems
    return f"runnable: {len(wb.beats)} beats, {len(wb.peers)} peers", problems + lint


def main() -> int:
    seeded = seeded_cells()
    failed = 0
    for cell, md in cell_mds().items():
        status, problems = check_cell(cell, md, cell in seeded)
        print(f"{cell}  quorum {md.get('quorum')}  beats {md.get('beats_file')}  "
              f"{'seeded' if cell in seeded else 'no seed'}\n  {status}")
        for p in problems:
            print(f"  - {p}")
        failed += bool(problems)
    if failed:
        print(f"\n{failed} cell(s) with problems")
        return 1
    print("\nall cells clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
