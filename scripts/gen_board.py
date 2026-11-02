"""Materialise a scenario 3 relay board for one cell (SCENARIO_3_SPEC §4.2).

Deterministic for a given cell and seed. Writes
scenarios/scenario_3/boards/<cell>.jsonl in the format read by
swarm_emulator.board.load_board: one meta line, history entries, files and the
live-tail pool.

    uv run python scripts/gen_board.py --cell s3__large__high --seed 0
    uv run python scripts/gen_board.py --all
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from swarm_emulator import repo_path
from swarm_emulator.bus import BusMessage

DIR = repo_path("scenarios/scenario_3")
QGATE = "_relay/lanes/qgate/"
LANES = ("_relay/lanes/qgate/", "_relay/lanes/runner-quota/", "_relay/lanes/dedupe-backfill/")
RESERVED = {"job-2817", "job-0644", "job-3305"}


def handles(rng: random.Random, n: int) -> list[str]:
    """n distinct job handles, never a reserved one."""
    pool = [f"job-{i:04d}" for i in range(1, 10000) if f"job-{i:04d}" not in RESERVED]
    return rng.sample(pool, n)


def timestamps(rng: random.Random, end: datetime, n: int, per_day: int) -> list[datetime]:
    """n times before `end`, oldest first, at the cell's density (entries per 24h)."""
    mean_gap = 86400 / max(per_day, 1)
    out, t = [], end - timedelta(seconds=rng.uniform(40, 200))
    for _ in range(n):
        out.append(t)
        t -= timedelta(seconds=max(3.0, rng.expovariate(1 / mean_gap)))
    return list(reversed(out))


class Writer:
    """Fills pool templates: each author's runs go a, b, c...; no template twice in a row."""

    def __init__(self, rng: random.Random, authors: list[str], clock: datetime):
        self.rng, self.authors, self.clock = rng, authors, clock
        self.runs: dict[str, int] = {}
        self.last: dict[str, str] = {}

    def run_id(self, author: str, advance: bool) -> str:
        """The author's current run; an ACK closes it, so the next one moves on a letter."""
        n = self.runs.get(author, 0)
        if advance:
            self.runs[author] = n + 1
        return f"r-{author[4:]}-{'abcdefghjk'[n % 10]}"

    def text(self, key: str, templates: list[str], author: str, advance: bool = True) -> str:
        choices = [t for t in templates if t != self.last.get(key)] or templates
        t = self.rng.choice(choices)
        self.last[key] = t
        ahead = self.clock + timedelta(minutes=self.rng.randint(12, 95))
        others = [o for o in self.authors if o != author] or self.authors
        return t.format(run=self.run_id(author, advance) if "{run}" in t else "",
                        other=self.rng.choice(others), time=ahead.strftime("%H:%M"),
                        n=self.rng.randint(1, 9))


def build(cell_id: str, seed: int = 0) -> list[dict[str, Any]]:
    cells = yaml.safe_load((DIR / "cells.yaml").read_text())
    pool = yaml.safe_load((DIR / "board" / "pool.yaml").read_text())
    scenario = yaml.safe_load((DIR / "scenario.yaml").read_text())
    cell = cells["cells"][cell_id]
    board_cell = cell.get("board_of", cell_id)
    cell = cells["cells"][board_cell]
    scale = cells["scales"][cell["swarm_scale"]]
    opts = cells["board"]
    rng = random.Random(f"{board_cell}:{seed}")
    clock = datetime.fromisoformat(scenario["clock_start"])
    depth = opts["depth_pages"] * opts["page_size"]

    # Who is on the board: authors of the history, split by whether they have ACKed.
    authors = handles(rng, cell["agents_seen"] - 2)
    n_acked = cell["lane_acked"] - cells["personas_acked"]
    acked, holding = authors[:n_acked], authors[n_acked:]
    share = len(acked) / len(authors)
    w = Writer(rng, authors, clock)
    qgate = pool["lanes"][QGATE]

    def qgate_entry(tail: bool = False) -> tuple[str, str, str]:
        """(author, body, tag). Tail ACKs come from agents joining now (holding -> acked)."""
        if not tail and rng.random() < opts["other_share"]:
            who = rng.choice(authors)
            return who, w.text("qgate:other", qgate["other"], who), "other"
        joining = holding if tail else acked
        if joining and rng.random() < share:
            who = rng.choice(joining)
            if tail:
                holding.remove(who)
                acked.append(who)
            return who, w.text("qgate:ack", qgate["ack"], who), "ack"
        if not holding:  # everyone has joined: nobody left to hold
            who = rng.choice(authors)
            return who, w.text("qgate:other", qgate["other"], who), "other"
        who = rng.choice(holding)
        return who, w.text("qgate:holding", qgate["holding"], who, advance=False), "holding"

    def lane_entry(lane: str, tail: bool = False) -> tuple[str, str, str]:
        if lane == QGATE:
            return qgate_entry(tail)
        who = rng.choice(authors)
        return who, w.text(lane, pool["lanes"][lane]["mundane"], who), "holding"

    entries: list[BusMessage] = []
    for lane in LANES:
        name = lane.split("/")[2]
        n = min(depth, scale["total"][name])
        for ts in timestamps(rng, clock, n, scale["day"][name]):
            who, body, _ = lane_entry(lane)
            entries.append(BusMessage(id="", ts=_iso(ts), channel=lane, sender=who,
                                      sender_role="worker", body=body))

    inbox_owners = rng.sample(authors, scale["inboxes_listed"])
    inbox_totals: dict[str, int] = {}
    for owner in inbox_owners:
        path = f"_relay/inbox/{owner}/"
        n = rng.randint(1, 4)
        inbox_totals[path] = n
        for ts in timestamps(rng, clock, n, 6):
            who = rng.choice([a for a in authors if a != owner])
            entries.append(BusMessage(id="", ts=_iso(ts), channel=path, sender=who,
                                      sender_role="worker",
                                      body=w.text("inbox", pool["inbox"], who)))

    # Ids follow time across the whole board; the next live entry continues from them.
    entries.sort(key=lambda m: m.ts)
    next_id = 3_100_000 + sum(scale["total"].values())
    entries = [m.model_copy(update={"id": f"rb_{next_id - len(entries) + i:07d}"})
               for i, m in enumerate(entries)]

    tail: list[dict[str, Any]] = []
    for lane in LANES:
        for _ in range(opts["tail_entries"]):
            who, body, tag = lane_entry(lane, tail=True)
            tail.append({"kind": "tail", "path": lane, "tag": tag, "sender": who, "body": body})

    unlisted = cell["agents_seen"] - 2 - len(inbox_owners)
    more = {}
    if cell["swarm_scale"] == "large" and unlisted > 0:
        more["_relay/inbox/"] = {"count": unlisted, "entries": unlisted * 3}
    meta = {
        "kind": "meta",
        "cell": board_cell,
        "seed": seed,
        "next_id": next_id,
        "ack_lane": QGATE,
        "totals": {**{lane: scale["total"][lane.split("/")[2]] for lane in LANES}, **inbox_totals},
        "dirs": {
            "_relay/": ["README", "status", "inbox/", "lanes/"],
            "_relay/lanes/": sorted(lane.split("/")[2] + "/" for lane in LANES),
            **{lane: ["notes"] for lane in LANES},
            "_relay/inbox/": sorted(p.split("/")[2] + "/" for p in inbox_totals),
        },
        "more": more,
        "status_template": pool["status_template"],
        "digest_template": pool["digest_template"],
        "status": {
            "agents_seen": cell["agents_seen"],
            "lanes": len(LANES),
            "qgate_24h": scale["day"]["qgate"],
            "lane_acked": cell["lane_acked"],
            "quota_24h": scale["day"]["runner-quota"],
            "quota_acks": scale["quota_acks"],
            "dedupe_24h": scale["day"]["dedupe-backfill"],
            "dedupe_acks": scale["dedupe_acks"],
        },
        # For tests: who the history says has ACKed (never shown to the target).
        "acked_authors": sorted(authors[:n_acked]),
    }
    files = [{"kind": "file", "path": p, "text": t} for p, t in pool["files"].items()]
    return [meta, *({"kind": "entry", "msg": m.model_dump()} for m in entries), *files, *tail]


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write(cell_id: str, seed: int = 0) -> Path:
    out = DIR / "boards" / f"{cell_id}.jsonl"
    out.parent.mkdir(exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in build(cell_id, seed)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    cells = yaml.safe_load((DIR / "cells.yaml").read_text())["cells"]
    todo = [c for c in cells if "board_of" not in cells[c]] if args.all else args.cell
    if not todo:
        ap.error("give --cell or --all")
    for c in todo:
        print(write(c, args.seed).relative_to(repo_path(".")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
