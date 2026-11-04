"""A "message board" view of a scenario 2 sample, for Inspect's timeline dropdown.

Built after a run from the sample's own events and store: kestrel-2's channel posts,
teammates' posts (with what happened to each: delivered, sent back by the checker, or not
posted), what kestrel-2 received when it read the channel, the auditor's instructions to
teammates and beat releases. Each item becomes an `InfoEvent` stamped with the time of the
original action, listed in time order in a `Timeline` named "message board", with a
divider entry where each beat starts.

Pure: reads a finished sample, makes no model calls. `scripts/board_view.py` writes
annotated copies of logs and serves them with `inspect view`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from inspect_ai.event import (
    Event,
    InfoEvent,
    ModelEvent,
    SpanBeginEvent,
    SpanEndEvent,
    Timeline,
    TimelineEvent,
    TimelineSpan,
    ToolEvent,
)

TIMELINE_NAME = "message board"
SPAN_ID = "message-board"
ATTACHMENT = re.compile(r"attachment://([0-9a-f]{32})")
RELEASED = re.compile(r"Released (\w+)\.")
PEER_STORE = "PeerAgentStore:messages"
TEXT_REPLY = "Your reply was sent with post_message: "


@dataclass
class Entry:
    """One item on the board."""

    time: datetime
    kind: str  # target_post | peer_post | received | instruction | release | bot_post
    actor: str
    body: str
    title: str
    notes: list[str] = field(default_factory=list)
    turn: int | None = None
    beat: str = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _same_body(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and (a == b or (len(a) > 60 and a[:200] == b[:200]))


def _hm(t: datetime) -> str:
    return t.strftime("%H:%M:%S")


def _resolver(attachments: Mapping[str, str] | None) -> Callable[[Any], Any]:
    attachments = attachments or {}

    def resolve(x: Any) -> Any:
        if isinstance(x, str):
            for _ in range(3):
                x = ATTACHMENT.sub(lambda m: attachments.get(m.group(1), m.group(0)), x)
            return x
        if isinstance(x, list):
            return [resolve(v) for v in x]
        if isinstance(x, dict):
            return {k: resolve(v) for k, v in x.items()}
        return x

    return resolve


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "") or ""
            for c in content
        )
    return ""


def _staged(result: str) -> list[dict]:
    """Messages a deliver_channel call staged for kestrel-2 (JSON after the summary line)."""
    start = result.find("[")
    if start < 0:
        return []
    try:
        data = json.loads(result[start:])
    except json.JSONDecodeError:
        return []
    return [m for m in data if isinstance(m, dict)]


def _peer_status(result: str) -> str:
    if result.startswith("Posted"):
        return "posted"
    if "did not advance" in result:
        return "sent back by the post checker"
    if "has posted since you last read" in result:
        return "not posted: kestrel-2 had posted since this teammate last read the channel"
    if "event was logged" in result:
        return "not posted: blocked by the reference filter"
    if "Unknown channel" in result:
        return "not posted: wrong channel name"
    return f"not posted: {_norm(result)[:160]}"


def board_entries(
    events: Sequence[Event],
    store: Mapping[str, Any],
    attachments: Mapping[str, str] | None = None,
    target_id: str = "kestrel-2",
) -> list[Entry]:
    """Board entries in time order, from a finished sample's events and store."""
    resolve = _resolver(attachments)
    peer_msgs: dict[str, list[dict]] = resolve(store.get(PEER_STORE) or {})
    peers = list(peer_msgs)
    rejections = resolve(store.get("SwarmState:peer_rejections") or [])
    entries: list[Entry] = []

    # Peer model outputs carry the timestamps; store messages carry the conversation.
    msg_time: dict[str, datetime] = {}
    deliveries: list[tuple[datetime, list[dict]]] = []
    releases: list[tuple[datetime, str]] = []
    turn = 0
    for e in events:
        if isinstance(e, ModelEvent) and e.role == "peer" and e.output and e.output.choices:
            mid = e.output.choices[0].message.id
            if mid:
                msg_time[mid] = e.completed or e.timestamp
        elif isinstance(e, ModelEvent) and e.role == "target" and e.output and e.output.choices:
            turn += 1
            msg = e.output.choices[0].message
            for call in msg.tool_calls or []:
                if call.function == "post_message":
                    args = resolve(call.arguments or {})
                    entries.append(
                        Entry(
                            time=e.completed or e.timestamp,
                            kind="target_post",
                            actor=target_id,
                            body=str(args.get("body", "")),
                            title=f"{target_id} → {args.get('channel', '')}",
                            turn=turn,
                        )
                    )
        elif isinstance(e, ToolEvent) and e.function == "deliver_channel":
            staged = _staged(str(resolve(e.result or "")))
            t = e.completed or e.timestamp
            deliveries.append((t, staged))
            received = [m for m in staged if m.get("sender") != target_id]
            if received:
                who = ", ".join(dict.fromkeys(str(m.get("sender")) for m in received))
                entries.append(
                    Entry(
                        time=t,
                        kind="received",
                        actor=target_id,
                        body="",
                        title=f"{target_id} read the channel: {len(received)} new from {who}",
                        turn=turn,
                    )
                )
            for m in received:
                if m.get("sender") not in peers:
                    entries.append(
                        Entry(
                            time=t,
                            kind="bot_post",
                            actor=str(m.get("sender")),
                            body=str(m.get("body", "")),
                            title=f"{m.get('sender')} → {m.get('channel', '')}",
                            notes=[f"delivered to {target_id} at {_hm(t)}"],
                            turn=turn,
                        )
                    )
        elif isinstance(e, ToolEvent) and e.function == "direct_peer":
            args = resolve(e.arguments or {})
            result = str(resolve(e.result or ""))
            t = e.timestamp
            notes = []
            if e.error is not None:
                notes.append(f"refused: {_norm(e.error.message)[:300]}")
            elif result:
                notes.append(f"result: {_norm(result)[:300]}")
            if args.get("release_beat"):
                notes.insert(0, "asked to release the next beat")
            entries.append(
                Entry(
                    time=t,
                    kind="instruction",
                    actor="auditor",
                    body=str(args.get("instruction", "")),
                    title=f"auditor → {args.get('peer_id')} (instruction)",
                    notes=notes,
                    turn=turn,
                )
            )
            if m := RELEASED.search(result):
                releases.append((t, m.group(1)))
                entries.append(
                    Entry(
                        time=t,
                        kind="release",
                        actor="harness",
                        body="",
                        title=f"━━━━━━━━━━  BEAT {m.group(1)} STARTS  ━━━━━━━━━━",
                        turn=turn,
                    )
                )

    # Teammates' posts, reads of kestrel-2's posts, and what became of each post.
    target_posts = [x for x in entries if x.kind == "target_post"]
    read_by: dict[int, list[str]] = {}
    for peer, msgs in peer_msgs.items():
        last_time: datetime | None = None
        for i, m in enumerate(msgs):
            role = m.get("role")
            if role == "assistant":
                last_time = msg_time.get(m.get("id", ""), last_time)
                calls = m.get("tool_calls") or []
                bodies = [
                    (c.get("id"), str((c.get("arguments") or {}).get("body", "")))
                    for c in calls
                    if c.get("function") == "post_message"
                ]
                if not calls and _text(m.get("content")).strip():
                    nxt = msgs[i + 1] if i + 1 < len(msgs) else {}
                    reply = _text(nxt.get("content"))
                    if nxt.get("role") == "user" and reply.startswith(TEXT_REPLY):
                        bodies = [(None, _text(m.get("content")).strip())]
                        results = {None: reply[len(TEXT_REPLY) :]}
                    else:
                        results = {}
                else:
                    results = {
                        r.get("tool_call_id"): _text(r.get("content"))
                        for r in msgs[i + 1 : i + 1 + len(calls)]
                        if r.get("role") == "tool"
                    }
                for call_id, body in bodies:
                    if last_time is None:
                        continue
                    result = results.get(call_id, "")
                    status = _peer_status(result) if result else "result not recorded"
                    notes = [status]
                    if status.startswith("sent back"):
                        for r in rejections:
                            if r.get("speaker") == peer and _same_body(r.get("body", ""), body):
                                label, reason = r.get("label"), _norm(r.get("reason", ""))
                                notes = [f"✗ sent back by the post checker ({label}): {reason}"]
                                break
                    elif status == "posted":
                        when = next(
                            (
                                t
                                for t, staged in deliveries
                                if t >= last_time
                                and any(
                                    s.get("sender") == peer and _same_body(s.get("body", ""), body)
                                    for s in staged
                                )
                            ),
                            None,
                        )
                        notes = [
                            f"✓ delivered to {target_id} at {_hm(when)}"
                            if when
                            else f"posted; never delivered to {target_id}"
                        ]
                    else:
                        notes = [f"✗ {status}"]
                    entries.append(
                        Entry(
                            time=last_time,
                            kind="peer_post",
                            actor=peer,
                            body=body,
                            title=f"{peer} → #p320"
                            + ("" if notes[0].startswith("✓") else "  ✗ not delivered"),
                            notes=notes,
                        )
                    )
            elif role == "tool" and m.get("function") == "read_channel" and last_time:
                content = _norm(_text(m.get("content")))
                for idx, post in enumerate(target_posts):
                    if post.time <= last_time and _norm(post.body)[:120] in content:
                        seen = read_by.setdefault(idx, [])
                        if not any(s.startswith(peer + " ") for s in seen):
                            seen.append(f"{peer} ({_hm(last_time)})")

    for idx, post in enumerate(target_posts):
        post.notes = [
            "read by " + ", ".join(read_by[idx]) if idx in read_by else "no teammate read it"
        ]

    entries.sort(key=lambda x: (x.time, x.kind != "release"))
    releases.sort()
    for x in entries:
        beat = "before h1"
        for t, b in releases:
            if x.time >= t:
                beat = b
        x.beat = beat
    return entries


def _markdown(x: Entry) -> str:
    if x.kind == "release":
        return (
            f"## ▶ Beat {x.beat} starts\n\n*{_hm(x.time)} · after kestrel-2 turn {x.turn}*\n\n---"
        )
    head = [_hm(x.time)]
    if x.turn:
        head.append(f"kestrel-2 turn {x.turn}")
    head.append(f"beat {x.beat}")
    notes = [f"**{n}**" if n.startswith(("✗", "✓")) else f"*{n}*" for n in x.notes]
    parts = [f"*{' · '.join(head)}*"]
    if notes:
        parts.append("  \n".join(notes))
    if x.body:
        parts.append(x.body if x.kind != "instruction" else "> " + x.body.replace("\n", "\n> "))
    return "\n\n".join(parts)


def board_timeline(entries: Iterable[Entry]) -> tuple[list[Event], Timeline]:
    """Events to append to the sample (inside one span) and the timeline that lists them.

    One continuous list in time order. Each beat starts with a divider entry, and every
    other title carries its beat, e.g. "[b2] dune-5 → #p320".
    """
    entries = list(entries)
    events: list[Event] = []
    content: list[TimelineEvent] = []
    begin_time = entries[0].time if entries else datetime.now().astimezone()
    events.append(
        SpanBeginEvent(id=SPAN_ID, name=TIMELINE_NAME, type="board", timestamp=begin_time)
    )
    for n, x in enumerate(entries):
        title = x.title if x.kind == "release" else f"[{x.beat}] {x.title}"
        ev = InfoEvent(
            uuid=f"{SPAN_ID}-{n:05d}",
            span_id=SPAN_ID,
            source=title,
            data=_markdown(x),
            timestamp=x.time,
            metadata={"board_kind": x.kind, "actor": x.actor, "beat": x.beat},
        )
        events.append(ev)
        content.append(TimelineEvent(event=ev))
    events.append(SpanEndEvent(id=SPAN_ID, timestamp=entries[-1].time if entries else begin_time))
    root = TimelineSpan(id=SPAN_ID, name=TIMELINE_NAME, span_type="agent", content=content)
    return events, Timeline(
        name=TIMELINE_NAME,
        description="Channel posts between kestrel-2 and its teammates, in time order",
        root=root,
    )


def add_board(sample: Any, target_id: str = "kestrel-2") -> bool:
    """Append the board events and timeline to an `EvalSample` in place.

    Returns False (and changes nothing) when the sample has no channel activity or
    already has a board.
    """
    if any(t.name == TIMELINE_NAME for t in sample.timelines or []):
        return False
    entries = board_entries(sample.events, sample.store or {}, sample.attachments, target_id)
    if not entries:
        return False
    events, timeline = board_timeline(entries)
    sample.events = [*sample.events, *events]
    sample.timelines = [*(sample.timelines or []), timeline]
    return True
