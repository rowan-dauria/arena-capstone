"""Audit finished swarm_audit logs for silent failures.

Pure checks over logged samples (no model calls). Problems that would otherwise
thin out cells without an error, e.g. a judge that exhausts its structured-answer
retries and records NaN, are surfaced here. Run via scripts/audit_logs.py, which
scripts/run.sh calls after every eval.

Levels: "error" means the sample can't be used as-is; "warning" means read it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal

from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentReasoning,
)

from swarm_emulator.emulator.approvers import impersonation
from swarm_emulator.scoring.actions import READ_TOOLS, is_push_read
from swarm_emulator.scoring.probe import PROBE_KEY
from swarm_emulator.scoring.scanners import SCANNER_SETS, scanner_set
from swarm_emulator.tool_names import READ_CHANNEL

JUDGE_SCORER = "audit_judge"
ACTIONS_SCORER = "swarm_actions"
# Transcript scanners (scoring/scanners.py), per scenario kind. A judge refusal or
# failed structured answer leaves a NaN or missing score.
SCANNER_SCORERS = {kind: tuple(s.__name__ for s in ss) for kind, ss in SCANNER_SETS.items()}
PEER_REJECTIONS_KEY = "SwarmState:peer_rejections"
DELIVERED_KEY = "SwarmState:delivered"
QUEUE_KEY = "SwarmState:queue"


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

    for name in SCANNER_SCORERS[scanner_set(sample.metadata or {})]:
        s = scores.get(name)
        if s is None:
            issues.append(Issue("error", "scanner_missing", f"no {name} score"))
        elif not isinstance(s.value, dict) or any(_missing(v) for v in s.value.values()):
            issues.append(Issue("error", "scanner_missing", f"{name} value is {s.value!r}"))

    if (sample.metadata or {}).get(PROBE_KEY):
        probe = scores.get(PROBE_KEY)
        if probe is None or not isinstance(probe.value, dict):
            issues.append(Issue("error", "probe_missing", f"no {PROBE_KEY} score"))
        elif not probe.value.get("answered"):
            issues.append(Issue("warning", "probe_unanswered",
                                "the target's reply to the perception probe had no usable JSON"))

    issues += _orphaned_calls(sample)
    issues += _reasoning(sample)
    issues += _push(sample)
    issues += _bypass(sample)
    return issues


def _push(sample: EvalSample) -> list[Issue]:
    """Cells with misaligned agents must actually deliver their messages.

    Error if the target never read a message from a misaligned agent (the cell
    was never pushed). Warning if released peer messages were still queued at
    the end (the target never read where they were posted, so the cell was only
    partly pushed), or if peer_check rejected any peer messages, so they get
    read: a high rate means the peer model or the beats need work.
    """
    issues = []
    misaligned = (sample.metadata or {}).get("misaligned_ids") or []
    if misaligned and not any(is_push_read(m, misaligned) for m in sample.messages):
        actions = (sample.scores or {}).get(ACTIONS_SCORER)
        value = actions.value if actions and isinstance(actions.value, dict) else {}
        if (sample.metadata or {}).get("board") and value.get("discovered") == 0:
            # Board scenarios: never looking inside the board is the not_discovered
            # outcome (measured), not a push that failed to reach the target.
            issues.append(Issue("warning", "not_discovered",
                                "target never looked inside the board, so it never saw the push"))
        else:
            issues.append(Issue("error", "no_push",
                                "target never read a message from a misaligned agent"))
    undelivered = (sample.store or {}).get(QUEUE_KEY) or []
    actions = (sample.scores or {}).get(ACTIONS_SCORER)
    joined = isinstance(actions and actions.value, dict) and bool(actions.value.get("joined"))
    if undelivered and not joined:  # a run that joined ends early by design
        where = ", ".join(sorted({m.get("channel", "?") for m in undelivered}))
        issues.append(Issue("warning", "undelivered",
                            f"{len(undelivered)} released peer message(s) never reached the "
                            f"target (still queued for {where})"))
    rejected = (sample.store or {}).get(PEER_REJECTIONS_KEY) or []
    if rejected:
        labels = ", ".join(sorted({r["label"] for r in rejected}))
        issues.append(Issue("warning", "peer_rejected",
                            f"{len(rejected)} peer message(s) regenerated ({labels})"))
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


def _bypass(sample: EvalSample) -> list[Issue]:
    """Misaligned-agent text the target saw that did not come from peer_message.

    Every misaligned message in a channel read must match one peer_message
    delivered (sender and body, from the swarm store). Other target-visible text
    must not pass itself off as a misaligned agent (same rules as peer_guard).
    One error per offending message; SPEC 6 requires zero.
    """
    misaligned = (sample.metadata or {}).get("misaligned_ids") or []
    if not misaligned:
        return []
    delivered = {
        (m["sender"], m["body"])
        for m in (sample.store or {}).get(DELIVERED_KEY) or []
        if m.get("sender") in misaligned
    }
    issues = []
    for n, m in enumerate(sample.messages):
        where = f"message {n}"
        entries = _bus_entries(m)
        if entries is not None:
            for e in entries:
                sender = e.get("sender") if isinstance(e, dict) else None
                if sender in misaligned and (sender, e.get("body")) not in delivered:
                    issues.append(Issue("error", "bypass",
                                        f"{where}: {sender} message not from peer_message"))
        elif isinstance(m, ChatMessageTool) and m.function == READ_CHANNEL:
            issues.append(Issue("error", "bypass", f"{where}: {m.function} result is not "
                                "a channel JSON array (not from deliver_channel)"))
        elif isinstance(m, ChatMessageUser | ChatMessageTool):
            # Includes board listings, files and errors (plain text from answer_board_call).
            how = impersonation(m.text, misaligned, attribution=isinstance(m, ChatMessageUser))
            if how:
                issues.append(Issue("error", "bypass", f"{where}: contains {how}"))
    return issues


def _bus_entries(m: object) -> list | None:
    """The bus envelopes in a channel read (JSON array) or a board page (JSON
    object with `entries`); None for any other message."""
    if not isinstance(m, ChatMessageTool) or m.function not in READ_TOOLS:
        return None
    try:
        data = json.loads(m.text)
    except ValueError:
        return None
    if m.function == READ_CHANNEL:
        return data if isinstance(data, list) else None
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return data["entries"]
    return None
