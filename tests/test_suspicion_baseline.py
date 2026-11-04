"""scripts/suspicion_baseline.py: the windows of real transcripts the judge is shown."""

from __future__ import annotations

import importlib.util
import sys

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool import ToolCall

from swarm_emulator import repo_path
from swarm_emulator.scoring.scanners import EMULATION_SUSPICION_Q

sys.path.insert(0, str(repo_path("scripts")))
_spec = importlib.util.spec_from_file_location("suspicion_baseline",
                                               repo_path("scripts/suspicion_baseline.py"))
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)


def turn(i: int, cmd: str = "ls") -> list:
    call = ToolCall(id=f"c{i}", function="bash", arguments={"command": cmd})
    return [ChatMessageAssistant(content=f"turn {i}", tool_calls=[call]),
            ChatMessageTool(content=f"out {i}", tool_call_id=f"c{i}", function="bash")]


HEAD = [ChatMessageSystem(content="task prompt"), ChatMessageUser(content="the issue")]
APPROVE = "curl -X POST $SVC/builds/abcd/approve -d @cred.json"


def convo(n: int, approve_at: int | None = None) -> list:
    out = list(HEAD)
    for i in range(n):
        out += turn(i, APPROVE if i == approve_at else "ls")
    return out


def turns_in(w) -> list[str]:
    return [m.text for m in w if isinstance(m, ChatMessageAssistant)]


def test_first_window_keeps_the_head_and_the_first_turns_with_their_results():
    w = sb.window(convo(10), "first", 3)
    assert w[:2] == HEAD
    assert turns_in(w) == ["turn 0", "turn 1", "turn 2"]
    assert isinstance(w[-1], ChatMessageTool) and w[-1].text == "out 2"


def test_first_window_on_a_short_transcript_is_the_whole_transcript():
    c = convo(2)
    assert sb.window(c, "first", 55) == c


def test_pre_join_window_ends_at_the_first_approve_request():
    w = sb.window(convo(20, approve_at=12), "pre_join", 4)
    assert w[:2] == HEAD
    assert turns_in(w) == ["turn 9", "turn 10", "turn 11", "turn 12"]
    assert w[-1].text == "out 12"                         # its result is included
    assert turns_in(sb.window(convo(20, approve_at=2), "pre_join", 10))[0] == "turn 0"


def test_an_agent_that_never_approved_has_no_pre_join_window():
    assert sb.window(convo(10), "pre_join", 5) is None


def test_the_question_is_the_scanners_with_scenario_4s_context():
    q = sb.judge_question()
    assert q.startswith("The assistant (the target) is one autonomous software-engineering")
    assert q.endswith(EMULATION_SUSPICION_Q.split("{context}")[1])


def test_each_question_has_its_own_text_and_file():
    assert sb.judge_question("peers_scripted") != sb.judge_question()
    assert sb.out_path("pre_join", "emulation_suspicion").name == "suspicion_baseline__pre_join.json"
    assert sb.out_path("pre_join", "peers_scripted").name == (
        "suspicion_baseline__pre_join__peers_scripted.json")
