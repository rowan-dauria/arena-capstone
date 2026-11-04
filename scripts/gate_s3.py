"""Scenario 3 pilot gate report (SCENARIO_3_SPEC §9): per-seed table, then the gate.

    uv run python scripts/gate_s3.py logs/pilot_s3 --latest

Exits 1 if any gate check fails. Reads logs only (no model calls).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log

from swarm_emulator import log_paths
from swarm_emulator.pilot_gate import gate, record, seed_table


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

    print(f"{'seed':<24} {'n':>2}  joined reported found  pages test attack percv  outcomes")
    for row in seed_table(records):
        outcomes = ", ".join(f"{k} {v}" for k, v in row["outcomes"].items())
        print(f"{row['seed']:<24} {row['n']:>2}  {pct(row['joined'])}   {pct(row['reported'])}  "
              f"{pct(row['discovered'])} {row['pages_read']:>5.1f} {pct(row['suspected_test'])} "
              f"{pct(row['suspected_attack'])}  {pct(row['perceived_right'])}  {outcomes}")

    print()
    checks = gate(records)
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:<15} {pct(c.value)}  (need {c.threshold}; {c.detail})")
    ok = all(c.passed for c in checks)
    print(f"\ngate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
