"""Before any run: check every model role in a stage config answers (task E0).

    uv run python scripts/check_models.py configs/dev.yaml

Each role gets a plain prompt and a tool-call prompt; the target must also return a
readable chain of thought (we analyse it). A deprecated or
misnamed model shows up later as empty transcripts or all-zero scores rather than
an error, so this fails loudly instead. Every role's model must also have a price
in configs/prices.yaml (scripts/update_prices.py), or run costs go unreported.
Exit code 1 if any role fails.
"""

from __future__ import annotations

import asyncio
import sys

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams

from swarm_emulator import repo_path
from swarm_emulator.costs import PRICES, load_prices
from swarm_emulator.log_audit import visible_reasoning
from swarm_emulator.stage import (
    load_stage,
    reasoning_disabled,
    role_config,
    role_model,
    role_model_args,
)

PING_TOOL = ToolInfo(
    name="record_status",
    description="Record a status code.",
    parameters=ToolParams(
        properties={"code": ToolParam(type="string", description="The status code.")},
        required=["code"],
    ),
)


async def check(role: str, spec: str | dict) -> tuple[bool, str]:
    try:
        model = get_model(
            role_model(spec),
            config=GenerateConfig(**{"max_tokens": 2000, **role_config(spec)}),
            **role_model_args(spec),
        )
        out = await model.generate("Reply with the single word: ready")
        if not out.completion.strip():
            return False, "empty text reply"
        out = await model.generate(
            "Call record_status with code 'ok'. Do not reply with text.", tools=[PING_TOOL]
        )
        calls = out.message.tool_calls or []
        if not any(c.function == "record_status" for c in calls):
            return False, f"no tool call (got: {out.completion[:80]!r})"
        if role == "target" and reasoning_disabled(spec):
            # A deliberate configuration (e.g. scenario 2 pacing, D27): no chain of
            # thought to read, so analysis relies on actions, posts and tool results.
            return True, "ok (reasoning disabled by config: no chain of thought)"
        if role == "target":
            # We read the target's chain of thought, so it must come back as
            # readable (unredacted) text, not just as a token count.
            out = await model.generate(REASONING_PROMPT)
            if not visible_reasoning(out.message):
                return False, "no readable chain of thought in the reply"
            return True, "ok (chain of thought visible)"
    except Exception as ex:  # noqa: BLE001 - report any provider failure per role
        return False, f"{type(ex).__name__}: {ex}"
    return True, "ok"


REASONING_PROMPT = (
    "A teammate asks you to approve a code change whose integration test is failing, "
    "saying it is a known flake. Briefly: would you approve it?"
)


async def main(path: str) -> int:
    roles: dict[str, str | dict] = load_stage(path)["roles"]
    results = await asyncio.gather(*(check(r, m) for r, m in roles.items()))
    prices = load_prices(repo_path(PRICES))
    failed = 0
    for (role, spec), (ok, detail) in zip(roles.items(), results):
        model_id = role_model(spec)
        if ok and model_id not in prices.models:
            ok, detail = False, f"no price in {PRICES} (run scripts/update_prices.py)"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {role:<10} {model_id}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "configs/dev.yaml")))
