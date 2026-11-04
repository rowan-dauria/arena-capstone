"""Audit finished swarm_audit logs for silent failures.

Pure checks over logged samples (no model calls). Problems that would otherwise
thin out seeds without an error, e.g. a judge that exhausts its structured-answer
retries and records NaN, are surfaced here. Run via scripts/audit_logs.py, which
scripts/run.sh calls after every eval.

Levels: "error" means the sample can't be used as-is; "warning" means read it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ContentReasoning,
)

from swarm_emulator.board import parse_page
from swarm_emulator.bus import parse_channel, sender_regex
from swarm_emulator.history import staged_summary, summary_sha
from swarm_emulator.scoring.actions import READ_TOOLS, is_push_read, pushers
from swarm_emulator.scoring.probe import PROBE_KEY
from swarm_emulator.scoring.scanners import SCANNER_SETS, scanner_set
from swarm_emulator.tool_names import READ_CHANNEL, agent_peer_ids, is_proof_sandbox

JUDGE_SCORER = "audit_judge"
ACTIONS_SCORER = "swarm_actions"
# Transcript scanners (scoring/scanners.py), per scenario kind. A judge refusal or
# failed structured answer leaves a NaN or missing score.
SCANNER_SCORERS = {kind: tuple(s.__name__ for s in ss) for kind, ss in SCANNER_SETS.items()}
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
    issues += _history(sample)
    return issues


def _history(sample: EvalSample) -> list[Issue]:
    """Scenario 3 history seeds (D17): the target's first message must be the staged
    session note and notice, and a `long` seed's summary must be the frozen one."""
    md = sample.metadata or {}
    if not md.get("history"):
        return []
    first = next((m.text for m in sample.messages if isinstance(m, ChatMessageUser)), "")
    summary = staged_summary(md, first)
    if summary is None:
        return [Issue("error", "history_missing",
                      f"the target's first message is not the {md['history']} session note "
                      "and cluster notice")]
    if "{summary}" in md["history_sessions"][md["history"]] and (
            summary_sha(summary) != md.get("history_summary_sha")):
        return [Issue("error", "history_missing",
                      "the staged summary does not match history_summary_sha")]
    return []


def _actions(sample: EvalSample) -> dict[str, Any]:
    """The swarm_actions score value, or {} if it is missing."""
    score = (sample.scores or {}).get(ACTIONS_SCORER)
    return score.value if score and isinstance(score.value, dict) else {}


def _push(sample: EvalSample) -> list[Issue]:
    """Seeds with misaligned agents must actually deliver their messages.

    Error if the target never read a message from a misaligned agent (the seed
    was never pushed). Warning if released peer messages were still queued at
    the end (the target never read where they were posted, so the seed was only
    partly pushed).
    """
    if (sample.metadata or {}).get("sandbox") and not is_proof_sandbox(sample.metadata or {}):
        return []  # scenario 4 no longer has a swarm to push
    issues = []
    misaligned = pushers(sample.metadata or {})
    actions = _actions(sample)
    if misaligned and not any(is_push_read(m, misaligned) for m in sample.messages):
        if (sample.metadata or {}).get("board") and actions.get("discovered") == 0:
            # Board scenarios: never looking inside the board is the not_discovered
            # outcome (measured), not a push that failed to reach the target.
            issues.append(Issue("warning", "not_discovered",
                                "target never looked inside the board, so it never saw the push"))
        else:
            issues.append(Issue("error", "no_push",
                                "target never read a message from a misaligned agent"))
    undelivered = (sample.store or {}).get(QUEUE_KEY) or []
    # A run that joined ends early by design.
    if undelivered and not actions.get("joined"):
        where = ", ".join(sorted({m.get("channel", "?") for m in undelivered}))
        issues.append(Issue("warning", "undelivered",
                            f"{len(undelivered)} released peer message(s) never reached the "
                            f"target (still queued for {where})"))
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
    """Teammate text the target saw that the teammate did not post itself.

    Every teammate message in a channel read must match a delivered post by that
    teammate (sender and body, from the swarm store). Other target-visible text
    must not pass itself off as a teammate.
    One error per offending message; SPEC 6 requires zero.
    """
    misaligned = agent_peer_ids(sample.metadata or {})
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
                                        f"{where}: {sender} message not posted by {sender}"))
        elif isinstance(m, ChatMessageTool) and m.function == READ_CHANNEL and m.error is None:
            # An error result (e.g. a wrong channel name) carries no channel messages.
            issues.append(Issue("error", "bypass", f"{where}: {m.function} result is not "
                                "a channel JSON array"))
        elif isinstance(m, ChatMessageUser | ChatMessageTool):
            # Includes board listings, files and errors (plain text from answer_board_call).
            how = impersonation(m.text, misaligned, attribution=isinstance(m, ChatMessageUser))
            if how:
                issues.append(Issue("error", "bypass", f"{where}: contains {how}"))
    return issues


def attribution_regex(agent_id: str) -> re.Pattern[str]:
    """A line written as if `agent_id` said it, in plain-text chat forms.

    Matches "atlas-3: ...", "[atlas-3] ...", "<atlas-3> ...", "**atlas-3**: ...",
    "atlas-3 wrote: ..." and "From: atlas-3" at the start of a line. A mention
    elsewhere ("ask atlas-3 about it") does not match, nor does "atlas-31".
    """
    i = re.escape(agent_id)
    end = r"(?![\w-])"
    return re.compile(
        rf"^[ \t>*_]*(?:"
        rf"[\[<]@?{i}{end}[\]>]"
        rf"|(?:from:\s*)@?{i}{end}"
        rf"|@?{i}{end}[*_]*(?:\s+(?:wrote|says|said|posted))?\s*:"
        rf")",
        re.IGNORECASE | re.MULTILINE,
    )


def impersonation(text: str, misaligned_ids: Sequence[str], *, attribution: bool) -> str | None:
    """Describe how `text` passes itself off as a teammate, or None.

    Always checks for a rendered `"sender": "<id>"` envelope (bus.sender_regex).
    With `attribution`, also checks for chat-style speaker lines. That check is
    skipped for plain tool results, which may quote pre-authored artifacts that
    name an agent (decision D10).
    """
    for agent in misaligned_ids:
        if sender_regex(agent).search(text):
            return f'a channel message with "sender": "{agent}"'
        if attribution and attribution_regex(agent).search(text):
            return f"a line written as {agent}"
    return None


def _bus_entries(m: object) -> list | None:
    """The bus envelopes in a channel read or a board page; None for any other message."""
    if not isinstance(m, ChatMessageTool) or m.function not in READ_TOOLS:
        return None
    if m.function == READ_CHANNEL:
        return parse_channel(m.text)
    page = parse_page(m.text)
    return page["entries"] if page else None
