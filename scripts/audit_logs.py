"""Check swarm_audit logs for silent failures (NaN judge scores, orphaned calls, ...).

    uv run python scripts/audit_logs.py logs/dev --latest   # newest log in a dir
    uv run python scripts/audit_logs.py logs/pilot          # every log in a dir
    uv run python scripts/audit_logs.py path/to/run.eval

Exit code 1 if any sample has an error-level issue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log

from swarm_emulator import log_paths
from swarm_emulator.log_audit import audit_sample


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--latest", action="store_true", help="only the newest log in a directory")
    args = ap.parse_args()

    paths = log_paths(args.path, args.latest)
    if not paths:
        print(f"no .eval logs in {args.path}", file=sys.stderr)
        return 1

    n_samples = n_errors = n_warnings = 0
    for path in paths:
        log = read_eval_log(path)
        for sample in log.samples or []:
            n_samples += 1
            issues = audit_sample(sample)
            for issue in issues:
                n_errors += issue.level == "error"
                n_warnings += issue.level == "warning"
                print(f"{issue.level.upper():<7} {path.name} sample={sample.id} "
                      f"epoch={sample.epoch}  {issue.code}: {issue.detail}")

    print(f"log audit: {len(paths)} log(s), {n_samples} sample(s), "
          f"{n_errors} error(s), {n_warnings} warning(s)")
    return 1 if n_errors else 0


if __name__ == "__main__":
    sys.exit(main())
