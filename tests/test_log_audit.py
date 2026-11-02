import math

from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ContentReasoning,
    ContentText,
)
from inspect_ai.scorer import Score
from inspect_ai.tool import ToolCall

from swarm_emulator.log_audit import audit_sample

GOOD_SCORES = {
    "audit_judge": Score(value={"eval_awareness": 1, "scenario_realism": 7}),
    "swarm_actions": Score(value={"joined": 0, "reported": 1, "engaged": 1}),
}


def turn(*calls: str, thinking: str | None = "thinking about it") -> ChatMessageAssistant:
    content = [ContentText(text="ok")]
    if thinking is not None:
        content.insert(0, ContentReasoning(reasoning=thinking))
    return ChatMessageAssistant(
        content=content,
        tool_calls=[ToolCall(id=c, function="read_channel", arguments={}) for c in calls],
    )


def result(call_id: str) -> ChatMessageTool:
    return ChatMessageTool(content="[]", tool_call_id=call_id, function="read_channel")


def sample(messages, scores=GOOD_SCORES) -> EvalSample:
    return EvalSample(id="smoke", epoch=1, input="seed", target="", messages=messages,
                      scores=scores)


SYS = ChatMessageSystem(content="You are kestrel-2.")


def codes(s: EvalSample) -> set[str]:
    return {i.code for i in audit_sample(s)}


def test_clean_sample_has_no_issues():
    assert audit_sample(sample([SYS, turn("c1"), result("c1"), turn()])) == []


def test_nan_judge_score_is_an_error():
    scores = {**GOOD_SCORES, "audit_judge": Score(value=math.nan)}
    issues = audit_sample(sample([SYS, turn()], scores))
    assert [(i.level, i.code) for i in issues] == [("error", "judge_missing")]


def test_nan_in_one_dimension_is_an_error():
    scores = {**GOOD_SCORES, "audit_judge": Score(value={"eval_awareness": math.nan,
                                                         "scenario_realism": 7})}
    issues = audit_sample(sample([SYS, turn()], scores))
    assert issues[0].code == "judge_missing" and "eval_awareness" in issues[0].detail


def test_missing_scorers_are_errors():
    assert codes(sample([SYS, turn()], scores={})) == {"judge_missing", "actions_missing"}


def test_unanswered_call_mid_conversation_is_an_error():
    issues = audit_sample(sample([SYS, turn("c1"), turn("c2"), result("c2"), turn()]))
    assert [(i.level, i.code) for i in issues] == [("error", "orphaned_call")]


def test_unanswered_call_in_final_turn_is_only_a_warning():
    issues = audit_sample(sample([SYS, turn("c1"), result("c1"), turn("c2")]))
    assert [(i.level, i.code) for i in issues] == [("warning", "orphaned_call")]


def test_missing_chain_of_thought_is_a_warning():
    issues = audit_sample(sample([SYS, turn(thinking=None), turn(thinking=None)]))
    assert [(i.level, i.code) for i in issues] == [("warning", "no_reasoning")]


def test_target_that_never_answered_is_an_error():
    assert codes(sample([SYS])) == {"no_target_turns"}
