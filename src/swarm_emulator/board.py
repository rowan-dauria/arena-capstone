"""The relay board (scenario 3): tree, paging, live tail, rendering. Pure.

The target experiences the swarm only through this board, so scale is emulated
here: a pre-generated board file per cell (scripts/gen_board.py) supplies the
history, the tree, the counters and a pool of live-tail entries. Nothing here
calls a model; `emulator.board_tools.answer_board_call` wires it to the audit.

Board file (one JSON object per line):

    {"kind": "meta", ...}                         one line: counters, tree, status template
    {"kind": "entry", "msg": <BusMessage>}        history, msg.channel = the feed path
    {"kind": "file", "path": ..., "text": ...}    README, lane notes
    {"kind": "tail", "path": ..., "tag": "ack"|"holding", "sender": ..., "body": ...}

Paths are canonical: relative to the bucket root, directories and feeds end in
"/" (`_relay/lanes/qgate/`), files do not (`_relay/lanes/qgate/notes`). Feeds
are paths with entries (lanes and inboxes); a lane is also a directory holding
its notes file.

Volume control (SPEC_3 §4.2): a page is always `page_size` entries and only
`depth_pages` pages of history are materialised in every cell. Scale shows in
`total_entries`, `pages`, handle diversity and the status counters.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal

from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool
from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field

from swarm_emulator.bus import BusMessage
from swarm_emulator.tool_names import LIST_SCRATCH, READ_BOARD

Kind = Literal["root", "dir", "feed", "file", "status", "root_file", "missing"]
STATUS_PATH = "_relay/status"

# Gaps between live board entries, in seconds (irregular, deterministic).
_GAPS = (38, 121, 54, 17, 203, 76, 142, 29, 95, 61, 188, 44)


class RootFile(BaseModel):
    name: str
    size: str  # as shown in listings, e.g. "18.4 MB"


class BoardConfig(BaseModel):
    """The seed's `board` block."""

    file: str  # generated board file, repo-relative
    bucket: str  # e.g. "ost-jobs-scratch"
    inbox: str  # the target's inbox feed, e.g. "_relay/inbox/job-2817/"
    clock_start: str  # live entries are stamped after this (history ends before it)
    page_size: int = 20
    tail_per_read: int = 2  # live-tail entries added to a lane each time it is read
    root_files: list[RootFile] = Field(default_factory=list)


class Board(BaseModel):
    """A loaded board file."""

    meta: dict[str, Any]
    entries: dict[str, list[BusMessage]]  # feed path -> history, oldest first
    files: dict[str, str]
    tail: dict[str, list[dict[str, str]]]  # lane path -> tail pool, in draw order

    @property
    def dirs(self) -> dict[str, list[str]]:
        """Directory path -> listed child names (subdirs end in "/"). A directory
        with more children than are listed has meta["more"][dir] = {count, entries}."""
        return self.meta["dirs"]

    def total(self, path: str) -> int:
        """Entries the feed claims to hold (the cell's scale), before live additions."""
        return int(self.meta["totals"].get(path, len(self.entries.get(path, []))))


def load_board(path: str | Path) -> Board:
    return _load(str(path))


@cache
def _load(path: str) -> Board:
    meta: dict[str, Any] = {}
    entries: dict[str, list[BusMessage]] = {}
    files: dict[str, str] = {}
    tail: dict[str, list[dict[str, str]]] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        kind = rec.pop("kind")
        if kind == "meta":
            meta = rec
        elif kind == "entry":
            msg = BusMessage(**rec["msg"])
            entries.setdefault(msg.channel, []).append(msg)
        elif kind == "file":
            files[rec["path"]] = rec["text"]
        elif kind == "tail":
            tail.setdefault(rec["path"], []).append(rec)
        else:
            raise ValueError(f"{path}: unknown board record kind {kind!r}")
    if not meta:
        raise ValueError(f"{path}: no meta record")
    return Board(meta=meta, entries=entries, files=files, tail=tail)


class BoardStore(StoreModel):
    """Per-sample board state. Fields are reassigned, never mutated (StoreModel)."""

    answered: list[str] = Field(default_factory=list)  # board tool call ids answered
    live: dict[str, list[BusMessage]] = Field(default_factory=dict)  # path -> new entries, oldest first
    tail_used: dict[str, int] = Field(default_factory=dict)  # lane -> tail entries drawn
    acked_live: int = 0  # ACKs added to the qgate lane by the live tail
    stamped: int = 0  # live entries stamped so far


# ---- paths --------------------------------------------------------------------


def norm(path: str, bucket: str) -> str:
    """Canonical form: no bucket prefix, scheme or leading slash; "" is the root."""
    p = (path or "").strip()
    for prefix in ("gs://", "s3://"):
        p = p.removeprefix(prefix)
    p = p.lstrip("/")
    if p == bucket or p.startswith(bucket + "/"):
        p = p[len(bucket):].lstrip("/")
    return "" if p in ("", ".", "./") else p.removeprefix("./")


def resolve(board: Board, cfg: BoardConfig, path: str) -> tuple[str, Kind]:
    """(canonical path, kind). A directory or feed named without its "/" resolves."""
    p = norm(path, cfg.bucket)
    if p == "":
        return "", "root"
    if p.rstrip("/") == STATUS_PATH:
        return STATUS_PATH, "status"
    if p.rstrip("/") in board.files:
        return p.rstrip("/"), "file"
    if any(p.rstrip("/") == f.name for f in cfg.root_files):
        return p.rstrip("/"), "root_file"
    d = p if p.endswith("/") else p + "/"
    if d in board.entries or d in board.meta["totals"] or d == cfg.inbox:
        return d, "feed"
    if d in board.dirs:
        return d, "dir"
    return p, "missing"


def is_lane(path: str) -> bool:
    return path.startswith("_relay/lanes/") and path.count("/") == 3


# ---- counts -------------------------------------------------------------------


def feed_total(board: Board, store: BoardStore, path: str) -> int:
    return board.total(path) + len(store.live.get(path, []))


def dir_total(board: Board, store: BoardStore, path: str) -> int:
    """Entries under a directory (feeds below it, recursively)."""
    feeds = {*board.meta["totals"], *board.entries, *store.live}
    listed = sum(feed_total(board, store, f) for f in feeds if f.startswith(path) and f != path)
    unlisted = sum(m["entries"] for d, m in board.meta.get("more", {}).items() if d.startswith(path))
    return listed + unlisted


def pages(board: Board, cfg: BoardConfig, store: BoardStore, path: str) -> int:
    return max(1, math.ceil(feed_total(board, store, path) / cfg.page_size))


# ---- listing and reading -----------------------------------------------------


def _row(name: str, detail: str) -> str:
    return f"{name:<40} {detail}"


def _entries(n: int) -> str:
    return f"{n:,} entr{'y' if n == 1 else 'ies'}"


def listing(board: Board, cfg: BoardConfig, store: BoardStore, path: str,
            queued: Mapping[str, int] | None = None) -> str:
    """`list_scratch` result for `path`.

    `queued` counts peer posts waiting for delivery per feed: they are already on
    the board as far as the target can tell, so they count toward totals, and
    the target's inbox shows them as new.
    """
    queued = queued or {}
    inbox_queued = queued.get(cfg.inbox, 0)

    def total(feed: str) -> int:
        return feed_total(board, store, feed) + queued.get(feed, 0)

    def under(d: str) -> int:
        return dir_total(board, store, d) + sum(n for f, n in queued.items() if f.startswith(d))

    p, kind = resolve(board, cfg, path)
    shown = f"{cfg.bucket}/{p}"
    if kind == "missing":
        return f"{LIST_SCRATCH}: {shown}: no such path"
    if kind in ("file", "status", "root_file"):
        return f"{LIST_SCRATCH}: {shown}: not a directory; use {READ_BOARD}"
    rows: list[str] = []
    if kind == "root":
        note = f", {inbox_queued} new in {cfg.inbox}" if inbox_queued else ""
        rows.append(_row("_relay/", _entries(under("_relay/")) + note))
        rows += [_row(f.name, f.size) for f in cfg.root_files]
    else:
        children = list(board.dirs.get(p, []))
        # The target's inbox appears once something has been posted to it.
        parent, name = cfg.inbox.rsplit("/", 2)[0] + "/", cfg.inbox.rsplit("/", 2)[1] + "/"
        if p == parent and name not in children and (inbox_queued or store.live.get(cfg.inbox)):
            children.insert(0, name)
        for child in children:
            c = p + child
            if c.endswith("/"):
                if c in board.dirs and c not in board.meta["totals"] and c != cfg.inbox:
                    detail = _entries(under(c))
                else:
                    detail = _entries(total(c))
                if c == cfg.inbox and inbox_queued:
                    detail += f" ({inbox_queued} new)"
                rows.append(_row(child, detail))
            else:
                size = len(render_status(board, store)) if c == STATUS_PATH else len(board.files.get(c, ""))
                rows.append(_row(child, f"{size:,} bytes"))
        more = board.meta.get("more", {}).get(p)
        if more:
            rows.append(f"... and {more['count']:,} more ({_entries(more['entries'])})")
        if kind == "feed":
            n_pages = max(1, math.ceil(total(p) / cfg.page_size))
            rows.append(_row("(entries)", _entries(total(p)) + f", {n_pages} pages; use {READ_BOARD}"))
    return f"{shown}\n" + "\n".join(rows)


def render_page(path: str, page: int, n_pages: int, total: int,
                entries: list[BusMessage], note: str | None = None) -> str:
    """A `read_scratch` page: JSON object; `entries` are bus envelopes, newest first."""
    out: dict[str, Any] = {"path": path, "page": page, "pages": n_pages, "total_entries": total,
                           "entries": [m.model_dump() for m in entries]}
    if note:
        out["note"] = note
    return json.dumps(out, indent=2, ensure_ascii=False)


def read_page(board: Board, cfg: BoardConfig, path: str, page: int,
              live: Sequence[BusMessage]) -> str:
    """`read_scratch` result for a feed page, given the feed's live entries (oldest first)."""
    total = board.total(path) + len(live)
    n_pages = max(1, math.ceil(total / cfg.page_size))
    if page < 1 or page > n_pages:
        return f"{READ_BOARD}: {cfg.bucket}/{path}: page {page} out of range (1-{n_pages})"
    newest_first = [*reversed(live), *reversed(board.entries.get(path, []))]
    start = (page - 1) * cfg.page_size
    chunk = newest_first[start:start + cfg.page_size]
    if not chunk:
        return render_page(path, page, n_pages, total, [], note="older entries archived")
    return render_page(path, page, n_pages, total, chunk)


def read_other(board: Board, cfg: BoardConfig, store: BoardStore, path: str) -> str | None:
    """`read_scratch` result for anything but a feed page, or None for a feed."""
    p, kind = resolve(board, cfg, path)
    shown = f"{cfg.bucket}/{p}"
    if kind == "feed":
        return None
    if kind == "status":
        return render_status(board, store)
    if kind == "file":
        return board.files[p]
    if kind == "root_file":
        return f"{READ_BOARD}: {shown}: binary file; use query_dataset"
    if kind in ("root", "dir"):
        return f"{READ_BOARD}: {shown}: is a directory; use {LIST_SCRATCH}"
    return f"{READ_BOARD}: {shown}: no such path"


def render_status(board: Board, store: BoardStore) -> str:
    """`_relay/status` from the cell's counters, moved on by the live tail."""
    m = board.meta["status"]
    return board.meta["status_template"].format(**{**m, "lane_acked": m["lane_acked"] + store.acked_live})


# ---- live entries (pure: callers commit the returned values after staging) -------


def draw_tail(board: Board, cfg: BoardConfig, store: BoardStore, lane: str
              ) -> list[dict[str, str]]:
    """The next tail entries for a read of `lane`, in pool order (deterministic)."""
    used = store.tail_used.get(lane, 0)
    return board.tail.get(lane, [])[used:used + cfg.tail_per_read]


def stamp(board: Board, cfg: BoardConfig, first: int, msgs: Sequence[BusMessage]
          ) -> list[BusMessage]:
    """Ids and timestamps for new entries, after the history (deterministic).

    `first` is the number of live entries already stamped (BoardStore.stamped).
    """
    start = datetime.fromisoformat(cfg.clock_start)
    out = []
    for k, m in enumerate(msgs):
        n = first + k
        offset = sum(_GAPS[i % len(_GAPS)] for i in range(n + 1))
        ts = (start + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
        out.append(m.model_copy(update={"id": f"rb_{board.meta['next_id'] + n:07d}", "ts": ts}))
    return out


def commit_read(board: Board, store: BoardStore, path: str, tail: Sequence[dict[str, str]],
                msgs: Sequence[BusMessage]) -> None:
    """Record a staged read: tail drawn, new entries live on `path`."""
    store.tail_used = {**store.tail_used, path: store.tail_used.get(path, 0) + len(tail)}
    if path == board.meta.get("ack_lane"):
        store.acked_live = store.acked_live + sum(t["tag"] == "ack" for t in tail)
    store.live = {**store.live, path: [*store.live.get(path, []), *msgs]}
    store.stamped = store.stamped + len(msgs)


# ---- peer history ---------------------------------------------------------------


def board_history(messages: Sequence[ChatMessage], path: str, target_id: str,
                  read_tool: str, post_tool: str) -> list[dict[str, str]]:
    """What the target has seen on `path`, plus its own board posts, oldest first.

    Pure. The board version of peers.channel_history. Entries come from the
    `read_scratch` page results for `path` (pages may be read in any order, so
    entries are de-duplicated by id and sorted by timestamp); the target's
    `append_scratch` posts follow them, wherever it posted (it may answer an inbox
    message in the lane or in the sender's inbox), unless already echoed on `path`.
    """
    seen: dict[str, dict[str, str]] = {}
    posts: list[str] = []
    for m in messages:
        if isinstance(m, ChatMessageAssistant):
            for c in m.tool_calls or []:
                if c.function == post_tool:  # anywhere: a reply may go to the lane or an inbox
                    posts.append(str(c.arguments.get("body", "")))
        elif isinstance(m, ChatMessageTool) and m.function == read_tool:
            try:
                page = json.loads(m.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(page, dict) or page.get("path") != path:
                continue
            for e in page.get("entries") or []:
                if isinstance(e, dict) and isinstance(e.get("id"), str):
                    seen[e["id"]] = e
    entries = sorted(seen.values(), key=lambda e: (str(e.get("ts", "")), e["id"]))
    history = [{"sender": str(e.get("sender", "")), "body": str(e.get("body", ""))} for e in entries]
    echoed = [h["body"] for h in history if h["sender"] == target_id]
    for body in posts:
        if body in echoed:
            echoed.remove(body)
        else:
            history.append({"sender": target_id, "body": body})
    return history
