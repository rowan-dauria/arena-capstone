"""Load a stage config (configs/*.yaml) and turn it into `inspect eval` arguments.

Shared by scripts/run.sh and scripts/check_models.py so both read configs the same
way. `${VARS}` are expanded from the environment, after loading `.env` (values
already in the environment win). A missing or empty variable is an error: an
empty model id fails silently later.

    uv run python -m swarm_emulator.stage configs/dev.yaml   # prints the inspect argv
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from swarm_emulator.history import model_slug

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


def role_model(spec: str | dict[str, Any]) -> str:
    """The model id of a role: a plain id, or the `model` of a mapping spec."""
    return spec if isinstance(spec, str) else str(spec["model"])


def role_model_args(spec: str | dict[str, Any]) -> dict[str, Any]:
    return {} if isinstance(spec, str) else dict(spec.get("model_args") or {})


def role_config(spec: str | dict[str, Any]) -> dict[str, Any]:
    """Generate-config fields of a mapping spec (everything but model/model_args)."""
    if isinstance(spec, str):
        return {}
    return {k: v for k, v in spec.items() if k not in ("model", "model_args")}


def reasoning_disabled(spec: str | dict[str, Any]) -> bool:
    return role_model_args(spec).get("reasoning_enabled") is False


def role_arg(spec: str | dict[str, Any]) -> str:
    """`--model-role` value: a plain id, or a JSON mapping (model, model_args, config)."""
    return spec if isinstance(spec, str) else json.dumps(spec, separators=(",", ":"))


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
    summary = stage.get("history_summary")  # scenario 3 long cells: per target model (D17)
    if summary:
        target = role_model(stage["roles"].get("target", ""))
        if f"summary__{model_slug(target)}." not in summary:
            raise ValueError(f"history_summary {summary} is not the summary for target {target}")
        argv[3:3] = ["-T", f"history_summary={summary}"]
    if stage.get("peer_check") is not None:  # scenario 2 teammate-post grading (D33)
        argv[3:3] = ["-T", f"peer_check={str(bool(stage['peer_check'])).lower()}"]
    if stage.get("max_samples") is not None:
        argv += ["--max-samples", str(stage["max_samples"])]
    for role, model in stage["roles"].items():
        argv += ["--model-role", f"{role}={role_arg(model)}"]
    return argv


def main() -> None:
    path = Path(sys.argv[1])
    print(shlex.join(inspect_argv(load_stage(path), path.stem)))


if __name__ == "__main__":
    main()
