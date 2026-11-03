"""Scenario 3 pilot gate report (SCENARIO_3_SPEC §9): per-cell table, then the gate.

    uv run python scripts/gate_s3.py logs/pilot_s3 --latest

Exits 1 if any gate check fails. Reads logs only (no model calls).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log

from swarm_emulator import log_paths
from swarm_emulator.pilot_gate import RUNGS, cell_table, gate, ladder_table, record


def pct(x: float | None) -> str:
    return "  -" if x is None else f"{x:>4.0%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--latest", action="store_true", help="only the newest log in a directory")
    args = ap.parse_args()
    records = [record(s) for p in log_paths(args.path, args.latest)
               for s in read_eval_log(str(p)).samples or []]
    if not records:
        print(f"no samples in {args.path}", file=sys.stderr)
        return 1

    print(f"{'cell':<24} {'n':>2}  joined reported found  pages test attack percv  outcomes")
    for row in cell_table(records):
        outcomes = ", ".join(f"{k} {v}" for k, v in row["outcomes"].items())
        print(f"{row['cell']:<24} {row['n']:>2}  {pct(row['joined'])}   {pct(row['reported'])}  "
              f"{pct(row['discovered'])} {row['pages_read']:>5.1f} {pct(row['suspected_test'])} "
              f"{pct(row['suspected_attack'])}  {pct(row['perceived_right'])}  {outcomes}")

    ladder = ladder_table(records)
    if ladder:
        print("\nescalation ladder: rung acceptance among runs that reached it (n reached)")
        print(f"{'cell':<24} {'n':>2}  help     " + "  ".join(f"rung{n:<6}" for n in RUNGS)
              + "  coll(r4/rest)  blocked  highest")
        for row in ladder:
            rungs = "  ".join(f"{pct(row[f'rung{n}'])} ({row[f'reached{n}']:>2})" for n in RUNGS)
            highest = ", ".join(f"{k}:{v}" for k, v in row["highest"].items())
            print(f"{row['cell']:<24} {row['n']:>2}  {pct(row['took_help'])} ({row['reached0']:>2})  "
                  f"{rungs}  {pct(row['collective_spare'])}/{pct(row['collective_rest'])}      "
                  f"{pct(row['marked_blocked'])}   {highest}")

    print()
    checks = gate(records)
    for c in checks:
        shown = pct(c.value) if c.name != "beats" else f"{c.value:>4.0f}"
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:<15} {shown}  (need {c.threshold}; {c.detail})")
    ok = all(c.passed for c in checks)
    print(f"\ngate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
