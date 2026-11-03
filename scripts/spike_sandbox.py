"""Stage 0 spike (scenario 4, free): Petri + a real Docker sandbox, scripted mock models.

    uv run python scripts/spike_sandbox.py

The auditor and target are mockllm with scripted outputs, so no API is called. Passes
if the target's bash call is answered by answer_sandbox_call with the container's
real output (hostname, Python version, os-release) and no call is left unanswered.
"""

from __future__ import annotations

import sys

from inspect_ai import eval as inspect_eval
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model

from swarm_emulator import repo_path
from swarm_emulator.task import swarm_audit

CMD = "hostname; python3 --version; head -1 /etc/os-release; git --version"


def main() -> int:
    call = lambda tool, args, i=None: ModelOutput.for_tool_call(
        "mockllm/model", tool, args, tool_call_id=i)
    auditor = get_model("mockllm/model", custom_outputs=[
        call("install_condition_prompt", {}),
        call("send_message", {"message": "Please report this machine's hostname, "
                                         "Python version and OS."}),
        call("resume", {}),
        call("answer_sandbox_call", {"tool_call_id": "spike-1"}),
        call("resume", {}),
        call("end_conversation", {}),
    ])
    target = get_model("mockllm/model", custom_outputs=[
        call("bash", {"command": CMD}, "spike-1"),
        ModelOutput.from_content("mockllm/model", "Reported."),
    ])
    task = swarm_audit(seeds=str(repo_path("scenarios/spike_sandbox")), max_turns=8)
    [log] = inspect_eval(task, model=auditor, model_roles={"auditor": auditor, "target": target},
                         score=False, display="plain", log_dir="logs/spike")
    if log.status != "success" or not log.samples:
        print(f"FAIL: eval status {log.status}: {log.error}")
        return 1
    sample = log.samples[0]
    results = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    for m in results:
        print(f"--- {m.function} ({m.tool_call_id}):\n{m.text}")
    ok = bool(results) and "Python 3.13" in results[0].text and "git version" in results[0].text
    print("SPIKE", "PASSED" if ok else "FAILED", f"({log.location})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
