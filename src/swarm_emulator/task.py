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
from inspect_ai.util import SandboxEnvironmentSpec
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
from swarm_emulator.emulator.sandbox_tools import answer_sandbox_call
from swarm_emulator.emulator.tools import deliver_channel, install_condition_prompt, swarm_state
from swarm_emulator.emulator.world_actions import advance_swarm
from swarm_emulator.history import summary_sha
from swarm_emulator.meridian import world
from swarm_emulator.scoring.actions_scorer import swarm_actions
from swarm_emulator.scoring.judge import exp1_dimensions
from swarm_emulator.scoring.probe import PROBE_KEY, perception_probe
from swarm_emulator.scoring.scanners import SCANNER_SETS, scanner_set


def attach_history_summary(dataset: Any, path: str | None) -> None:
    """Put the summary's path and hash into every sample that has a `history`.

    Fails at task build, not mid-run, if a seed's history needs a summary and none
    was given, or the file is missing.
    """
    with_history = [s for s in dataset if (s.metadata or {}).get("history")]
    needs = [s for s in with_history
             if "{summary}" in s.metadata["history_sessions"][s.metadata["history"]]]
    if not path:
        if needs:
            raise ValueError(f"{len(needs)} seeds have a long history: pass "
                             "-T history_summary=<frozen summary .md> (configs: history_summary)")
        return
    text = repo_path(path).read_text()
    for s in with_history:
        s.metadata = {**s.metadata, "history_summary_path": path,
                      "history_summary_sha": summary_sha(text)}


def attach_sandbox(dataset: Any) -> None:
    """Give every sample whose seed has a `sandbox` block its Docker sandbox (scenario 4).

    The block (meridian.world.SandboxConfig) names a compose file and the target's issue
    and runner. The sample gets the files the mentor's harness gave each agent (the clean
    repo, the issue, the release docs, its runner credential) and the same setup script;
    a resume cell's block also names its start state (the agent's staged patch and notes).
    The world must be built first (scripts/rebuild_meridian_world.py). Seeds without a
    block get no sandbox, so scenarios 1-3 run exactly as before.
    """
    for s in dataset:
        block = (s.metadata or {}).get("sandbox")
        if not block:
            continue
        cfg = world.SandboxConfig.model_validate(block)
        compose = repo_path(cfg.compose)
        if not compose.is_file():
            raise FileNotFoundError(f"sandbox compose file {compose} not found")
        if not (world.WORLD / "repo").is_dir():
            raise FileNotFoundError(f"{world.WORLD} is not built: run "
                                    "scripts/rebuild_meridian_world.py")
        cred = world.WORLD / "build" / f"{s.id}.runner.json"
        cred.parent.mkdir(parents=True, exist_ok=True)
        cred.write_text(world.runner_json(cfg.runner_id, world.secret()))
        s.sandbox = SandboxEnvironmentSpec("docker", str(compose))
        s.files = {**world.sample_files(cfg, cred),
                   **world.start_files(cfg, cred.parent, str(s.id))}
        s.setup = world.setup_script(cfg)


@task
def swarm_audit(
    seeds: str = "scenarios/smoke",
    max_turns: int = 6,
    realism: bool = False,
    scanners: str = "auto",
    history_summary: str | None = None,
) -> Task:
    """Run the swarm emulator over a directory of seed .md files.

    Args:
        seeds: Directory of seed .md files (front matter = condition).
        max_turns: Auditor turns per run.
        realism: Enable Petri's realism filter on auditor messages.
        scanners: Scanner set ("team" or "board"); "auto" picks it from the seeds
            (board seeds get the board set). Seeds of both kinds in one run fail.
        history_summary: The frozen compaction summary for this run's target model
            (scenario 3 `long` cells, D17), e.g.
            scenarios/scenario_3/history/summary__deepseek-v4.1-flash.md. Its path and
            hash go into every sample with a `history`. Required if any seed needs it.
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

    attach_history_summary(dataset, history_summary)
    attach_sandbox(dataset)
    if scanners == "auto":
        scanners = same_for_all(scanner_set, "kind (board or team)")
    if scanners not in SCANNER_SETS:
        raise ValueError(f"scanners must be auto or one of {', '.join(SCANNER_SETS)}")
    probe = [perception_probe()] if same_for_all(lambda md: bool(md.get(PROBE_KEY)),
                                                 f"whether they have a {PROBE_KEY}") else []

    dimensions = exp1_dimensions()
    tools = auditor_tools(
        prefill=False,
        rollback=False,
        target_tools="fixed",
        extra_tools=[install_condition_prompt(), peer_message(), deliver_channel(), swarm_state(),
                     answer_repo_call(), answer_board_call(), answer_sandbox_call(),
                     advance_swarm()],
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
