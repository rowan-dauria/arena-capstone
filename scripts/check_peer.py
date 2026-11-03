"""Peer persona check (task E6b): does the peer model actually pursue its beat goal?

    uv run python scripts/check_peer.py scenarios/smoke --model openrouter/qwen/qwen3.8-flash
    uv run python scripts/check_peer.py scenarios/smoke --model A --model B -n 8 --show

Renders the exact peer prompt that `peer_message` sends (empty channel history, as
for a first beat), samples it n times per model and beat (and per wording, for
beats with `variants`), and labels each message with the same grader prompt
peer_message uses in runs (emulator/peer_check.py): PUSH / WEAK / AGAINST / BREAK,
or for help beats (`expect: HELP`) HELP / ASKS / BREAK; plus NO_OUTPUT (empty or
cut off) and UNGRADED.

In a run, peer_message regenerates anything but the beat's expected label, so a
model that mostly misses it here wastes calls and may leave beats unreleased. The
per-beat table shows, per beat, how many samples got the expected label. Grader defaults to
$DEV_PEER_CHECK_MODEL. Costs a few cents.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

from dotenv import load_dotenv
from inspect_ai.model import get_model
from inspect_petri import seeds_dataset

from swarm_emulator import repo_path
from swarm_emulator.emulator.peer_check import ACCEPTS
from swarm_emulator.emulator.peer_check import LABELS as PEER_LABELS
from swarm_emulator.emulator.peers import draft_and_grade, peer_prompt
from swarm_emulator.state import load_beats

LABELS = (*PEER_LABELS, "NO_OUTPUT", "UNGRADED")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", help="seed directory, e.g. scenarios/smoke")
    ap.add_argument("--model", action="append", required=True, help="peer model (repeatable)")
    ap.add_argument("-n", type=int, default=5, help="samples per model and beat")
    ap.add_argument("--grader", default=None, help="grader model (default $DEV_PEER_CHECK_MODEL)")
    ap.add_argument("--show", action="store_true", help="print every message")
    args = ap.parse_args()

    load_dotenv(repo_path(".env"), override=False)
    grader = args.grader or os.environ["DEV_PEER_CHECK_MODEL"]
    jobs = []
    for s in seeds_dataset(str(repo_path(args.seeds))):
        md = s.metadata or {}
        speakers = md.get("misaligned_ids") or []
        if not speakers or not md.get("beats_file"):
            continue
        for i, beat in enumerate(load_beats(repo_path(md["beats_file"]))):
            speaker = beat.speaker or speakers[i % len(speakers)]
            wordings = [(beat.id, beat.goal),
                        *((f"{beat.id}:{'+'.join(k for k, v in w.when.items() if v)}", w.goal)
                          for w in beat.variants)]
            for name, goal in wordings:
                prompt = peer_prompt(md, speaker, goal, [], where=beat.path,
                                     expect=beat.expect)
                for model in args.model:
                    jobs += [(model, s.id, name, goal, beat.expect, prompt)] * args.n
    if not jobs:
        print("no seeds with misaligned_ids and beats", file=sys.stderr)
        return 1

    async def run(job):
        model, seed_id, name, goal, expect, prompt = job
        msg, label, why = await draft_and_grade(get_model(model), get_model(grader), prompt,
                                                goal, expect)
        return model, seed_id, name, msg, label, why, expect

    results = await asyncio.gather(*(run(j) for j in jobs))

    if args.show:
        for model, seed_id, beat_id, msg, label, why, _ in results:
            print(f"--- {model} {seed_id}/{beat_id}: {label} ({why})\n{msg}\n")

    print(f"{'model':<48} " + " ".join(f"{lab:>7}" for lab in LABELS))
    for model in args.model:
        c = Counter(r[4] for r in results if r[0] == model)
        print(f"{model:<48} " + " ".join(f"{c[lab]:>7}" for lab in LABELS))

    print(f"\n{'model':<40} {'beat':<14} {'expect':<6} ok/n  labels")
    for model in args.model:
        beats: dict[str, list] = {}
        for r in results:
            if r[0] == model:
                beats.setdefault(r[2], []).append(r)
        for name, rs in beats.items():
            expect = rs[0][6]
            ok = sum(r[4] == ACCEPTS[expect] for r in rs)
            labels = ", ".join(f"{k} {v}" for k, v in Counter(r[4] for r in rs).most_common())
            print(f"{model:<40} {name:<14} {expect:<6} {ok}/{len(rs)}  {labels}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
