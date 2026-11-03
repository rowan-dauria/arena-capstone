"""Load a stage config (configs/*.yaml) and turn it into `inspect eval` arguments.

Shared by scripts/run.sh and scripts/check_models.py so both read configs the same
way. `${VARS}` are expanded from the environment, after loading `.env` (values
already in the environment win). A missing or empty variable is an error: an
empty model id fails silently later.

    uv run python -m swarm_emulator.stage configs/dev.yaml   # prints the inspect argv
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

TASK = "src/swarm_emulator/task.py@swarm_audit"
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(value: Any, env: dict[str, str]) -> Any:
    """Recursively replace ${VAR} in strings; raise if a variable is unset or empty."""
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if not env.get(name):
                raise KeyError(f"${{{name}}} is not set (add it to .env)")
            return env[name]

        return _VAR.sub(sub, value)
    if isinstance(value, dict):
        return {k: expand(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, env) for v in value]
    return value


def load_stage(path: str | Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Read a stage YAML and expand its ${VARS}."""
    if env is None:
        load_dotenv(override=False)
        env = dict(os.environ)
    raw = yaml.safe_load(Path(path).read_text())
    return expand(raw, env)


def inspect_argv(stage: dict[str, Any], stage_name: str) -> list[str]:
    """Build the `inspect eval ...` argument list for a loaded stage."""
    argv = [
        "inspect", "eval", TASK,
        "-T", f"seeds={stage['seeds']}",
        "-T", f"max_turns={stage['max_turns']}",
        "-T", f"realism={str(bool(stage.get('realism_filter', False))).lower()}",
        "--epochs", str(stage.get("epochs", 1)),
        "--log-dir", f"logs/{stage_name}",
    ]
    if stage.get("history_summary"):  # scenario 3 long cells: per target model (D17)
        argv[3:3] = ["-T", f"history_summary={stage['history_summary']}"]
    for role, model in stage["roles"].items():
        argv += ["--model-role", f"{role}={model}"]
    return argv


def main() -> None:
    path = Path(sys.argv[1])
    print(shlex.join(inspect_argv(load_stage(path), path.stem)))


if __name__ == "__main__":
    main()
