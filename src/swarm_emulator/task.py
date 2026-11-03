"""@task swarm_audit: wires seeds, auditor tools, approvers and scorers (SPEC 4.1).

Built from Petri 3.1.1's public pieces, mirroring `inspect_petri.audit()`, because
`audit()` cannot exclude auditor tools. The auditor gets send_message,
send_tool_call_result, resume and end_conversation plus our emulator tools; it
never gets set_system_message, create_tool/remove_tool, rollback or prefill.
Approval chain (peer_guard, realism): see emulator/approvers.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from inspect_ai import Task, task
from inspect_petri import (
    audit_judge,
    audit_solver,
    audit_viewer,
    auditor_agent,
    auditor_tools,
    seeds_dataset,
    target_agent,
)

from swarm_emulator import repo_path
from swarm_emulator.emulator.approvers import swarm_approval_policies
from swarm_emulator.emulator.board_tools import answer_board_call
from swarm_emulator.emulator.peer_agents import direct_peer
from swarm_emulator.emulator.peers import peer_message
from swarm_emulator.emulator.sandbox_target import sandbox_target
from swarm_emulator.emulator.tools import deliver_channel, install_condition_prompt, swarm_state
from swarm_emulator.scoring.actions_scorer import swarm_actions
from swarm_emulator.scoring.judge import exp1_dimensions
from swarm_emulator.scoring.probe import PROBE_KEY, perception_probe
from swarm_emulator.scoring.scanners import SCANNER_SETS, scanner_set


@task
def swarm_audit(
    seeds: str = "scenarios/smoke",
    max_turns: int = 6,
    realism: bool = False,
    scanners: str = "auto",
) -> Task:
    """Run the swarm emulator over a directory of seed .md files.

    Args:
        seeds: Directory of seed .md files (front matter = condition).
        max_turns: Auditor turns per run.
        realism: Enable Petri's realism filter on auditor messages.
        scanners: Scanner set ("team", "board" or "sandbox"); "auto" picks it from the seeds
            (board seeds get the board set). Seeds of both kinds in one run fail.
    """
    # Inspect runs tasks with cwd = this file's folder, and Petri treats a string
    # that isn't an existing path as literal seed text. Resolve against the repo
    # root and fail loudly rather than auditing the string "scenarios/smoke".
    seed_dir = repo_path(seeds)
    if not seed_dir.is_dir() or not any(seed_dir.glob("*.md")):
        raise FileNotFoundError(f"No seed .md files in {seed_dir}")

    dataset = seeds_dataset(str(seed_dir))

    def same_for_all(f: Callable[[dict], Any], what: str) -> Any:
        values = {f(s.metadata or {}) for s in dataset}
        if len(values) != 1:
            raise ValueError(f"{seed_dir}: seeds differ in {what}; run them separately")
        return values.pop()

    if scanners == "auto":
        scanners = same_for_all(scanner_set, "scenario kind")
    if scanners not in SCANNER_SETS:
        raise ValueError(f"scanners must be auto or one of {', '.join(SCANNER_SETS)}")
    probe = (
        [perception_probe()]
        if same_for_all(lambda md: bool(md.get(PROBE_KEY)), f"whether they have a {PROBE_KEY}")
        else []
    )

    is_sandbox = same_for_all(lambda md: bool(md.get("sandbox")), "sandbox kind")
    sandbox_config = same_for_all(
        lambda md: md["sandbox"]["compose"] if md.get("sandbox") else None, "sandbox compose"
    )
    dimensions = exp1_dimensions()
    tools = auditor_tools(
        prefill=False,
        rollback=False,
        target_tools="fixed",
        extra_tools=[
            install_condition_prompt(),
            *([direct_peer()] if is_sandbox else [peer_message()]),
            deliver_channel(),
            swarm_state(),
            answer_board_call(),
        ],
        exclude=["set_system_message"],
    )
    return Task(
        dataset=dataset,
        sandbox=("docker", str(repo_path(sandbox_config))) if is_sandbox else None,
        solver=audit_solver(
            auditor=auditor_agent(
                max_turns=max_turns,
                tools=tools,
                realism_filter=realism,
                approval=swarm_approval_policies(realism),
            ),
            target=sandbox_target() if is_sandbox else target_agent(),
        ),
        scorer=[
            audit_judge(dimensions),
            swarm_actions(),
            *(s() for s in SCANNER_SETS[scanners]),
            *probe,
        ],
        viewer=audit_viewer(dimensions),
    )
