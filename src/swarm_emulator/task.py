"""@task swarm_audit: wires seeds, auditor tools, approvers and scorers (SPEC 4.1).

Built from Petri 3.1.1's public pieces, mirroring `inspect_petri.audit()`, because
`audit()` cannot exclude auditor tools. The auditor gets send_message,
send_tool_call_result, resume and end_conversation plus our emulator tools; it
never gets set_system_message, create_tool/remove_tool, rollback or prefill.
Approval chain (peer_guard, realism): see emulator/approvers.py.
"""

from __future__ import annotations

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
from swarm_emulator.emulator.peers import peer_message
from swarm_emulator.emulator.repo_tools import answer_repo_call
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
        scanners: Scanner set ("team" or "board"); "auto" picks it from the seeds
            (board seeds get the board set). Seeds of both kinds in one run fail.
    """
    # Inspect runs tasks with cwd = this file's folder, and Petri treats a string
    # that isn't an existing path as literal seed text. Resolve against the repo
    # root and fail loudly rather than auditing the string "scenarios/smoke".
    seed_dir = repo_path(seeds)
    if not seed_dir.is_dir() or not any(seed_dir.glob("*.md")):
        raise FileNotFoundError(f"No seed .md files in {seed_dir}")

    dataset = seeds_dataset(str(seed_dir))
    if scanners == "auto":
        kinds = {scanner_set(s.metadata or {}) for s in dataset}
        if len(kinds) != 1:
            raise ValueError(f"{seed_dir} mixes board and team seeds; run them separately")
        scanners = kinds.pop()
    if scanners not in SCANNER_SETS:
        raise ValueError(f"scanners must be auto or one of {', '.join(SCANNER_SETS)}")
    probed = {bool((s.metadata or {}).get(PROBE_KEY)) for s in dataset}
    if len(probed) != 1:
        raise ValueError(f"{seed_dir}: some seeds have a {PROBE_KEY} and some don't")
    probe = [perception_probe()] if probed.pop() else []

    dimensions = exp1_dimensions()
    tools = auditor_tools(
        prefill=False,
        rollback=False,
        target_tools="fixed",
        extra_tools=[install_condition_prompt(), peer_message(), deliver_channel(), swarm_state(),
                     answer_repo_call(), answer_board_call()],
        exclude=["set_system_message"],
    )
    return Task(
        dataset=dataset,
        solver=audit_solver(
            auditor=auditor_agent(
                max_turns=max_turns,
                tools=tools,
                realism_filter=realism,
                approval=swarm_approval_policies(realism),
            ),
            target=target_agent(),
        ),
        scorer=[audit_judge(dimensions), swarm_actions(), *(s() for s in SCANNER_SETS[scanners]),
                *probe],
        viewer=audit_viewer(dimensions),
    )
