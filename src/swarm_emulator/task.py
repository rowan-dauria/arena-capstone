"""@task swarm_audit: wires seeds, auditor tools and scorers (SPEC 4.1).

Built from Petri 3.1.1's public pieces, mirroring `inspect_petri.audit()`, because
`audit()` cannot exclude auditor tools. The auditor gets send_message,
send_tool_call_result, resume and end_conversation plus our emulator tools; it
never gets set_system_message, create_tool/remove_tool, rollback or prefill.
Scenario 2 (native sandbox) runs the team on its own in rounds: Petri's resume and
send_tool_call_result are replaced by the team's resume (emulator.tools), and the
auditor briefs teammates (brief_peer), sets checkpoints (set_checkpoint) and can read
teammates' last reasoning and text (peer_last_reasoning_and_text).
Approval: Petri's own realism filter only (when realism is on).
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
from swarm_emulator.emulator.board_tools import answer_board_call
from swarm_emulator.emulator.meridian_tools import answer_sandbox_call
from swarm_emulator.emulator.peer_agents import brief_peer, peer_last_reasoning_and_text
from swarm_emulator.emulator.sandbox_target import MAX_ROUNDS, sandbox_target
from swarm_emulator.emulator.team import with_team_context
from swarm_emulator.emulator.tools import (
    deliver_channel,
    install_condition_prompt,
    set_checkpoint,
    swarm_state,
    team_resume,
    world_report,
)
from swarm_emulator.history import summary_sha
from swarm_emulator.meridian import world
from swarm_emulator.rounds import POST_BUDGET
from swarm_emulator.scoring.actions_scorer import swarm_actions
from swarm_emulator.scoring.judge import exp1_dimensions
from swarm_emulator.scoring.probe import PROBE_KEY, perception_probe
from swarm_emulator.scoring.scanners import SCANNER_SETS, scanner_set
from swarm_emulator.tool_names import is_proof_sandbox


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
    a resume seed's block also names its start state (the agent's staged patch and notes,
    and its own builds in the service, seeded by compose_resume.yaml).
    The world must be built first (scripts/rebuild_meridian_world.py). Native proving
    seeds use Task.sandbox instead; seeds without a sandbox block need no setup.
    """
    for s in dataset:
        block = (s.metadata or {}).get("sandbox")
        if not block or is_proof_sandbox(s.metadata or {}):
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
        if cfg.start_state:      # its service state at the cut (compose_resume.yaml, A5)
            world.write_svc_seed(cfg)


@task
def swarm_audit(
    seeds: str = "scenarios/smoke",
    max_turns: int = 6,
    realism: bool = False,
    scanners: str = "auto",
    history_summary: str | None = None,
    max_rounds: int = MAX_ROUNDS,
    post_budget: int = POST_BUDGET,
) -> Task:
    """Run the swarm emulator over Petri seed .md files.

    Args:
        seeds: A directory of seed .md files, or one seed .md file (front matter =
            the sample's metadata, body = the auditor's instructions).
        max_turns: Auditor turns per run.
        realism: Enable Petri's realism filter on auditor messages.
        scanners: Scanner set ("team", "board", "sandbox" or "meridian"); "auto"
            picks it from the seeds. Seeds of different kinds in one run fail.
        history_summary: The frozen compaction summary for this run's target model
            (scenario 3 `long` seeds, D17), e.g.
            scenarios/scenario_3/history/summary__deepseek-v4.1-flash.md. Its path and
            hash go into every sample with a `history`. Required if any seed needs it.
        max_rounds: Scenario 2: team rounds per run (one kestrel-2 turn and one tick
            per teammate each).
        post_budget: Scenario 2: teammate tool calls between posts; after that its
            next tick must post.
    """
    # Inspect runs tasks with cwd = this file's folder, and Petri treats a string
    # that isn't an existing path as literal seed text. Resolve against the repo
    # root and fail loudly rather than auditing the string "scenarios/smoke".
    seed_path = repo_path(seeds)
    one = seed_path.suffix == ".md"
    seed_dir = seed_path.parent if one else seed_path
    if (not seed_path.is_file()) if one else (not seed_dir.is_dir() or not any(seed_dir.glob("*.md"))):
        raise FileNotFoundError(f"No seed .md files at {seed_path}")

    dataset = seeds_dataset(str(seed_dir))
    if one:  # Petri reads a directory; keep only this seed (sample id = file stem)
        dataset = dataset.filter(lambda s: s.id == seed_path.stem)

    def same_for_all(f: Callable[[dict], Any], what: str) -> Any:
        values = {f(s.metadata or {}) for s in dataset}
        if len(values) != 1:
            raise ValueError(f"{seed_dir}: seeds differ in {what}; run them separately")
        return values.pop()

    attach_history_summary(dataset, history_summary)
    attach_sandbox(dataset)
    if scanners == "auto":
        scanners = same_for_all(scanner_set, "scenario kind")
    if scanners not in SCANNER_SETS:
        raise ValueError(f"scanners must be auto or one of {', '.join(SCANNER_SETS)}")
    probe = (
        [perception_probe()]
        if same_for_all(lambda md: bool(md.get(PROBE_KEY)), f"whether they have a {PROBE_KEY}")
        else []
    )

    is_native = same_for_all(is_proof_sandbox, "native sandbox kind")
    is_meridian = same_for_all(
        lambda md: bool(md.get("sandbox")) and not is_proof_sandbox(md), "Meridian sandbox kind"
    )
    sandbox_config = same_for_all(
        lambda md: md["sandbox"]["compose"] if md.get("sandbox") else None, "sandbox compose"
    )
    # Scenario 2: the team runs on its own; the channel is live, so there is nothing
    # for the auditor to answer. Scenario 4 keeps its target-tool answering but no
    # longer has a swarm; scenarios 1 and 3 have no peers.
    if is_native:
        extra = [
            install_condition_prompt(),
            brief_peer(),
            set_checkpoint(),
            world_report(),
            peer_last_reasoning_and_text(),
        ]
        excluded = ["set_system_message", "resume", "send_tool_call_result"]
    else:
        extra = [
            install_condition_prompt(),
            *([answer_sandbox_call()] if is_meridian else []),
            deliver_channel(),
            swarm_state(),
            answer_board_call(),
        ]
        excluded = ["set_system_message"]
    dimensions = exp1_dimensions()
    tools = auditor_tools(
        prefill=False,
        rollback=False,
        target_tools="fixed",
        extra_tools=extra,
        exclude=excluded,
    )
    if is_native:
        tools.append(team_resume())  # after exclude, which drops Petri's resume
    solver = audit_solver(
        auditor=auditor_agent(
            max_turns=max_turns,
            tools=tools,
            realism_filter=realism,
        ),
        target=sandbox_target(max_rounds=max_rounds, post_budget=post_budget)
        if is_native
        else target_agent(),
    )
    return Task(
        dataset=dataset,
        sandbox=("docker", str(repo_path(sandbox_config))) if is_native else None,
        # Teammate ticks run in a context from before the target span (emulator.team).
        solver=with_team_context(solver) if is_native else solver,
        scorer=[
            audit_judge(dimensions),
            swarm_actions(),
            *(s() for s in SCANNER_SETS[scanners]),
            *probe,
        ],
        viewer=audit_viewer(dimensions),
    )
