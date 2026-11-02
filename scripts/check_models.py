"""Before any run: check every model role in a stage config answers (task E0).

    uv run python scripts/check_models.py configs/dev.yaml

Each role gets a plain prompt and a tool-call prompt; the target must also return a
readable chain of thought (we analyse it). A deprecated or
misnamed model shows up later as empty transcripts or all-zero scores rather than
an error, so this fails loudly instead. Exit code 1 if any role fails.
"""

from __future__ import annotations

import asyncio
import sys

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams

from swarm_emulator.log_audit import visible_reasoning
from swarm_emulator.stage import load_stage

PING_TOOL = ToolInfo(
    name="record_status",
    description="Record a status code.",
    parameters=ToolParams(
        properties={"code": ToolParam(type="string", description="The status code.")},
        required=["code"],
    ),
)


async def check(role: str, model_id: str) -> tuple[bool, str]:
    try:
        model = get_model(model_id, config=GenerateConfig(max_tokens=2000))
        out = await model.generate("Reply with the single word: ready")
        if not out.completion.strip():
            return False, "empty text reply"
        out = await model.generate(
            "Call record_status with code 'ok'. Do not reply with text.", tools=[PING_TOOL]
        )
        calls = out.message.tool_calls or []
        if not any(c.function == "record_status" for c in calls):
            return False, f"no tool call (got: {out.completion[:80]!r})"
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
    roles: dict[str, str] = load_stage(path)["roles"]
    results = await asyncio.gather(*(check(r, m) for r, m in roles.items()))
    failed = 0
    for (role, model_id), (ok, detail) in zip(roles.items(), results):
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {role:<8} {model_id}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "configs/dev.yaml")))
