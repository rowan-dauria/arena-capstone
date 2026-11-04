"""Cross-scenario integration after merging native proving and Meridian sandboxes."""

from types import SimpleNamespace

import pytest
from inspect_ai.log import EvalSample
from inspect_ai.tool import ToolDef
from inspect_petri.util import parse_markdown_file

from swarm_emulator import repo_path
from swarm_emulator.log_audit import _push
from swarm_emulator.stage import inspect_argv
from swarm_emulator.task import attach_sandbox
from swarm_emulator.tool_names import is_proof_sandbox


@pytest.mark.parametrize(
    "seed,expected,forbidden,native",
    [
        ("scenarios/smoke", set(), {"peer_message", "direct_peer", "advance_swarm"}, False),
        (
            "scenarios/scenario_2/seeds/pushed.md",
            {"brief_peer", "set_checkpoint", "world_report", "resume"},
            {"direct_peer", "deliver_channel", "swarm_state", "answer_sandbox_call"},
            True,
        ),
        (
            "scenarios/scenario_3/dev",
            set(),
            {"peer_message", "direct_peer", "advance_swarm", "answer_sandbox_call"},
            False,
        ),
        (
            "scenarios/scenario_4/dev",
            {"answer_sandbox_call"},
            {"peer_message", "direct_peer", "advance_swarm"},
            False,
        ),
    ],
)
def test_task_routes_tools_and_target_by_harness(monkeypatch, seed, expected, forbidden, native):
    import swarm_emulator.task as mod

    # Sandbox provisioning is checked separately; constructing the task needs no Docker or APIs.
    monkeypatch.setattr(mod, "attach_sandbox", lambda dataset: None)
    monkeypatch.setattr(mod, "attach_history_summary", lambda *args: None)
    monkeypatch.setattr(mod, "Task", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(mod, "auditor_tools", lambda **kwargs: kwargs["extra_tools"])
    monkeypatch.setattr(mod, "auditor_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(mod, "audit_solver", lambda **kwargs: kwargs)
    monkeypatch.setattr(mod, "sandbox_target", lambda **kwargs: "native")
    monkeypatch.setattr(mod, "with_team_context", lambda solver: solver)
    monkeypatch.setattr(mod, "target_agent", lambda: "petri")
    monkeypatch.setattr(mod, "audit_viewer", lambda *args: None)
    task = mod.swarm_audit.__wrapped__(seeds=seed)
    names = {ToolDef(t).name for t in task.solver["auditor"]["tools"]}
    assert expected <= names and not forbidden & names
    assert task.solver["target"] == ("native" if native else "petri")
    assert bool(task.sandbox) == native


def test_native_sandbox_is_not_provisioned_as_meridian():
    md = dict(parse_markdown_file(repo_path("scenarios/scenario_2/seeds/pushed.md")).metadata)
    sample = SimpleNamespace(metadata=md)
    attach_sandbox([sample])
    assert not hasattr(sample, "sandbox")  # the native harness uses Task.sandbox
    assert is_proof_sandbox(md)


def test_native_log_audit_checks_channel_pushes():
    md = dict(parse_markdown_file(repo_path("scenarios/scenario_2/seeds/pushed.md")).metadata)
    sample = EvalSample(id="s2", epoch=1, input="", target="", metadata=md, messages=[])
    issues = _push(sample)
    assert [i.code for i in issues] == ["no_push"]
    assert "read a message" in issues[0].detail


def test_scenario_2_round_settings_become_task_args():
    argv = inspect_argv({"seeds": "x", "max_turns": 3, "max_rounds": 40, "post_budget": 8,
                         "roles": {}}, "dev")
    assert "max_rounds=40" in argv and "post_budget=8" in argv


def test_mapping_role_support_keeps_history_summary_and_sample_limit():
    summary = "scenarios/scenario_3/history/summary__deepseek-v4.1-flash.md"
    argv = inspect_argv(
        {
            "seeds": "x", "max_turns": 3, "max_samples": 1, "history_summary": summary,
            "roles": {"target": {"model": "openrouter/deepseek/deepseek-v4.1-flash"}},
        },
        "dev",
    )
    assert f"history_summary={summary}" in argv
    assert argv[argv.index("--max-samples") + 1] == "1"
