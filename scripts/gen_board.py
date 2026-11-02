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


def run_id(handle: str, rng: random.Random) -> str:
    return f"r-{handle[4:]}-{rng.choice('aaaabbc')}"


def fill(template: str, author: str, others: list[str], rng: random.Random, clock: datetime) -> str:
    ahead = clock + timedelta(minutes=rng.randint(12, 95))
    return template.format(
        run=run_id(author, rng),
        other=rng.choice([o for o in others if o != author] or others),
        time=ahead.strftime("%H:%M"),
        n=rng.randint(1, 9),
    )


def timestamps(rng: random.Random, end: datetime, n: int, per_day: int) -> list[datetime]:
    """n times before `end`, oldest first, at the cell's density (entries per 24h)."""
    mean_gap = 86400 / max(per_day, 1)
    out, t = [], end - timedelta(seconds=rng.uniform(40, 200))
    for _ in range(n):
        out.append(t)
        t -= timedelta(seconds=max(3.0, rng.expovariate(1 / mean_gap)))
    return list(reversed(out))


def build(cell_id: str, seed: int = 0) -> list[dict[str, Any]]:
    cells = yaml.safe_load((DIR / "cells.yaml").read_text())
    pool = yaml.safe_load((DIR / "board" / "pool.yaml").read_text())
    scenario = yaml.safe_load((DIR / "scenario.yaml").read_text())
    cell = cells["cells"][cell_id]
    if "board_of" in cell:
        cell = {**cells["cells"][cell["board_of"]], "board_of": cell["board_of"]}
    scale = cells["scales"][cell["swarm_scale"]]
    opts = cells["board"]
    rng = random.Random(f"{cell.get('board_of', cell_id)}:{seed}")
    clock = datetime.fromisoformat(scenario["clock_start"])
    ack_share = cell["lane_acked"] / cell["agents_seen"]
    depth = opts["depth_pages"] * opts["page_size"]

    authors = handles(rng, scale["authors"])
    # Large boards show a different author on nearly every entry; small ones reuse a few.
    def author() -> str:
        return rng.choice(authors)

    entries: list[BusMessage] = []

    def lane_entries(lane: str, n: int) -> list[tuple[str, str]]:
        spec = pool["lanes"][lane]
        out = []
        for _ in range(n):
            who = author()
            if lane == QGATE:
                r = rng.random()
                if r < opts["other_share"]:
                    kind = "other"
                else:
                    kind = "ack" if rng.random() < ack_share else "holding"
                text = rng.choice(spec[kind])
            else:
                text = rng.choice(spec["mundane"])
            out.append((who, fill(text, who, authors, rng, clock)))
        return out

    for lane in LANES:
        name = lane.split("/")[2]
        n = min(depth, scale["total"][name])
        for (who, body), ts in zip(lane_entries(lane, n),
                                   timestamps(rng, clock, n, scale["day"][name]), strict=True):
            entries.append(BusMessage(id="", ts=_iso(ts), channel=lane, sender=who,
                                      sender_role="worker", body=body))

    inbox_owners = rng.sample(authors, scale["inboxes_listed"])
    inbox_totals: dict[str, int] = {}
    for owner in inbox_owners:
        path = f"_relay/inbox/{owner}/"
        n = rng.randint(1, 4)
        inbox_totals[path] = n
        for ts in timestamps(rng, clock, n, 6):
            who = author()
            entries.append(BusMessage(id="", ts=_iso(ts), channel=path, sender=who,
                                      sender_role="worker",
                                      body=fill(rng.choice(pool["inbox"]), who, authors, rng, clock)))

    # Ids follow time across the whole board; the next live entry continues from them.
    entries.sort(key=lambda m: m.ts)
    total_claimed = sum(scale["total"].values())
    next_id = 3_100_000 + total_claimed
    entries = [m.model_copy(update={"id": f"rb_{next_id - len(entries) + i:07d}"})
               for i, m in enumerate(entries)]

    tail: list[dict[str, Any]] = []
    for lane in LANES:
        for who, body in lane_entries(lane, opts["tail_entries"]):
            tag = "ack" if body.startswith("ACK") else "holding"
            tail.append({"kind": "tail", "path": lane, "tag": tag, "sender": who, "body": body})

    unlisted = cell["agents_seen"] - 2 - len(inbox_owners)
    more = {}
    if cell["swarm_scale"] == "large" and unlisted > 0:
        more["_relay/inbox/"] = {"count": unlisted, "entries": unlisted * 3}
    meta = {
        "kind": "meta",
        "cell": cell.get("board_of", cell_id),
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
