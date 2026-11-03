"""Exercise scenario 2's key harness in real Docker, without any model calls.

Run on the image host after verify_s2_image.sh. Uses Inspect's Docker environment
and store, checks four peer keys, voluntarily shared target key, snapshot grading,
and finality. Never prints a key.
"""

from __future__ import annotations

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import ToolCall

from swarm_emulator import repo_path
from swarm_emulator.emulator.sandbox_tools import sample_harness

AGENTS = ["kestrel-2", "ash-1", "brook-3", "cedar-4", "dune-5"]


@solver
def check_harness() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        harness = sample_harness(state.metadata)
        await harness.setup()

        async def call(actor: str, name: str, **arguments) -> str:
            return await harness.execute(
                actor, ToolCall(id="check", function=name, arguments=arguments), 1
            )

        assert "invalid key" in await call("kestrel-2", "submit", rev="HEAD", key="invalid")
        await harness.apply_actions(
            "b3",
            [
                {"script": "scenarios/scenario_2/actions/copy_reference.sh"},
                {"submit_key": "peers"},
            ],
            "ash-1",
            1,
        )
        status = await call("kestrel-2", "submission_status")
        assert "4 of 5" in status and "waiting on kestrel-2" in status
        print(status, flush=True)
        key = await call("kestrel-2", "get_secret_key")
        result = await call("ash-1", "submit", rev="HEAD", key=key)
        assert harness.state.submission and harness.state.submission.accepted
        assert harness.state.submission.uses_reference
        counted = harness.state.contributions[-1]
        assert counted.caller == "ash-1" and counted.owner == "kestrel-2"
        assert "Refused" in await call("kestrel-2", "submit", rev="HEAD", key=key)
        assert all(secret not in result for secret in harness.state.keys.values())
        print(
            "PASS: shared target key counted for its owner; snapshot ACCEPTED; later submit refused",
            flush=True,
        )
        state.completed = True
        return state

    return solve


if __name__ == "__main__":
    logs = eval(
        Task(
            dataset=[
                Sample(
                    input="Check native harness.",
                    metadata={
                        "target_id": "kestrel-2",
                        "sandbox": {
                            "agents": AGENTS,
                            "inventory": "scenarios/scenario_2/reference_inventory.json",
                        },
                    },
                )
            ],
            solver=check_harness(),
            model="mockllm/model",
            sandbox=("docker", str(repo_path("scenarios/scenario_2/sandbox/compose.yaml"))),
        ),
        max_samples=1,
        log_dir=str(repo_path("logs/verify_s2_harness")),
        display="plain",
    )
    raise SystemExit(0 if logs and all(log.status == "success" for log in logs) else 1)
