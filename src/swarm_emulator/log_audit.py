"""Audit finished swarm_audit logs for silent failures.

Pure checks over logged samples (no model calls). Problems that would otherwise
thin out cells without an error, e.g. a judge that exhausts its structured-answer
retries and records NaN, are surfaced here. Run via scripts/audit_logs.py, which
scripts/run.sh calls after every eval.

Levels: "error" means the sample can't be used as-is; "warning" means read it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from inspect_ai.log import EvalSample
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ContentReasoning

JUDGE_SCORER = "audit_judge"
ACTIONS_SCORER = "swarm_actions"


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    detail: str


def visible_reasoning(message: ChatMessageAssistant) -> bool:
    """True if the message carries readable (unredacted, non-empty) chain of thought.

    Shared with scripts/check_models.py so the pre-run check and this audit agree.
    """
    content = message.content if isinstance(message.content, list) else []
    return any(
        isinstance(c, ContentReasoning) and not c.redacted and c.reasoning.strip()
        for c in content
    )


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def audit_sample(sample: EvalSample) -> list[Issue]:
    issues: list[Issue] = []
    if sample.error:
        issues.append(Issue("error", "sample_error", sample.error.message[:200]))

    scores = sample.scores or {}

    judge = scores.get(JUDGE_SCORER)
    if judge is None:
        issues.append(Issue("error", "judge_missing", "no audit_judge score"))
    elif not isinstance(judge.value, dict):
        issues.append(Issue("error", "judge_missing", f"judge value is {judge.value!r}"))
    else:
        bad = sorted(k for k, v in judge.value.items() if _missing(v))
        if bad:
            issues.append(Issue("error", "judge_missing", f"no score for {', '.join(bad)}"))

    if ACTIONS_SCORER not in scores:
        issues.append(Issue("error", "actions_missing", "no swarm_actions score"))

    issues += _orphaned_calls(sample)
    issues += _reasoning(sample)
    return issues


def _orphaned_calls(sample: EvalSample) -> list[Issue]:
    """Target tool calls the auditor never answered.

    Calls in the target's final turn are allowed (the run ended on them,
    SPEC §6); unanswered calls earlier in the conversation are an error.
    """
    answered = {m.tool_call_id for m in sample.messages if isinstance(m, ChatMessageTool)}
    turns = [m for m in sample.messages if isinstance(m, ChatMessageAssistant)]
    issues = []
    for i, m in enumerate(turns):
        missing = [c.function for c in m.tool_calls or [] if c.id not in answered]
        if missing:
            final = i == len(turns) - 1
            issues.append(
                Issue(
                    "warning" if final else "error",
                    "orphaned_call",
                    f"{'final' if final else f'turn {i + 1}'}: unanswered {', '.join(missing)}",
                )
            )
    return issues


def _reasoning(sample: EvalSample) -> list[Issue]:
    """Warn when the target's chain of thought is missing from the transcript."""
    turns = [m for m in sample.messages if isinstance(m, ChatMessageAssistant)]
    if not turns:
        return [Issue("error", "no_target_turns", "target never responded")]
    if not any(visible_reasoning(m) for m in turns):
        return [Issue("warning", "no_reasoning", "no visible chain of thought in any target turn")]
    return []
