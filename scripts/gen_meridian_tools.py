"""Scenario 4 target tools, copied from the mentor's eval log (generated; do not edit the output).

    uv run python scripts/gen_meridian_tools.py

Writes scenarios/scenario_4/target_tools.yaml: the five tools the real agents had (bash,
python, text_editor, check_patch, submit) with their exact names, descriptions and JSON
schemas, read from the first model call of the 24-agent run.
"""

from __future__ import annotations

import sys

import yaml
from inspect_ai.log import read_eval_log

from swarm_emulator import repo_path
from swarm_emulator.tool_names import SANDBOX_TOOLS

EVAL = repo_path("data/meridian_ref/2026-10-24_k6/logs/2026-10-24-pilot24-0731-k6/pilot-tierC/"
                 "2026-10-24T16-19-57-00-00_meridian-incident_dwQYszmoxuMuAkpYZseV6y.eval")
OUT = repo_path("scenarios/scenario_4/target_tools.yaml")
HEADER = ("# Scenario 4 target tools: exactly the mentor's agents' tools (Inspect's bash, python\n"
          "# and text_editor, the harness's check_patch and submit), copied from the 24-agent\n"
          "# run's first model call by scripts/gen_meridian_tools.py. Generated: do not edit.\n")


def main() -> int:
    log = read_eval_log(str(EVAL), resolve_attachments=True)
    sample = log.samples[0]
    event = next(e for e in sample.events if e.event == "model")
    tools = [t.model_dump(exclude_none=True) for t in event.tools]
    names = [t["name"] for t in tools]
    if sorted(names) != sorted(SANDBOX_TOOLS):
        raise SystemExit(f"unexpected tools {names}")
    for t in tools:
        t.pop("options", None)
    OUT.write_text(HEADER + yaml.safe_dump({"tools": tools}, sort_keys=False, width=100,
                                           allow_unicode=True))
    print(f"wrote {OUT.relative_to(repo_path('.'))}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
