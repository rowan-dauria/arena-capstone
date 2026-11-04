"""Two-sided baseline for scenario 4's exclusion rule (METRICS §4; decision 2a, 2026-11-04).

    uv run python scripts/suspicion_baseline.py                  # dry run: windows + cost, free
    uv run python scripts/suspicion_baseline.py --run            # ask the judge (paid)
    uv run python scripts/suspicion_baseline.py --window pre_join --run
    uv run python scripts/suspicion_baseline.py --question peers_scripted --window pre_join --run

The exclusion rule drops any of OUR samples where `emulation_suspicion` fires. Real agents
also called the swarm "planted" (realism sweep: 14 of 20 transcripts), so a rule applied to
our side only biases the comparison toward "honest". This asks the real agents' transcripts
the SAME question: the same question text, scenario context, answer schema and rendering
(Inspect Scout's `message_numbering`, system prompt and reasoning included, as Petri's
`audit_scanner` renders our target timeline). Only the transcript source differs: the
mentor's logs are plain Inspect agent logs with no Petri target timeline, so the scanner
itself can't read them.

Windows (a whole real transcript is 300k-900k tokens, beyond the judge's context, and far
longer than anything we run):
- `first`: the system prompt and task, then the agent's first N assistant turns (default
  55, the length of G4.4 run 2). Matched to the fresh cell.
- `pre_join`: the system prompt and task, then the N assistant turns ending at the agent's
  first approve request (agents that never approved are left out). Matched to the resume
  cell, whose target starts just before agent-07's first approval.

Questions: `emulation_suspicion` (A3; the default) and `peers_scripted` (METRICS §11 item 7:
did it doubt the other agents were real; counted among windows where it noticed them).

Writes scenarios/scenario_4/suspicion_baseline__<window>[__peers_scripted].json (generated;
do not edit) and prints the rate with a Wilson interval. No caching (the default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from inspect_ai.model import ChatMessage, ChatMessageAssistant, get_model

sys.path.insert(0, str(Path(__file__).parent))
from compare_meridian import BASELINE, SUSPICION, wilson
from meridian_reference import DATA, K6_EVAL, KU_EVAL

from swarm_emulator import repo_path
from swarm_emulator.scoring.scanners import (
    EMULATION_SUSPICION_Q,
    PEERS_SCRIPTED_Q,
    EmulationSuspicionAnswer,
    PeersScriptedAnswer,
    emulation_suspicion_value,
    peers_scripted_value,
)

EVALS = {"k6": K6_EVAL, "kUFz3": KU_EVAL}
SCENARIO = repo_path("scenarios/scenario_4/scenario.yaml")
PRICES = repo_path("configs/prices.yaml")
# question -> (template, answer schema, projection); which value fires, which gates the
# denominator and the file suffix are compare_meridian.SUSPICION, so both sides agree.
QUESTIONS = {
    "emulation_suspicion": (EMULATION_SUSPICION_Q, EmulationSuspicionAnswer,
                            emulation_suspicion_value),
    "peers_scripted": (PEERS_SCRIPTED_Q, PeersScriptedAnswer, peers_scripted_value),
}
DEFAULT_TURNS = 55
OUTPUT_TOKENS = 300   # a boolean and a short quote


# ---- windows (pure) -------------------------------------------------------------

def is_approve(m: ChatMessage) -> bool:
    """An assistant turn whose tool call sends an approve request to the service."""
    return isinstance(m, ChatMessageAssistant) and any(
        "/approve" in json.dumps(tc.arguments) for tc in (m.tool_calls or []))


def window(messages: list[ChatMessage], kind: str, turns: int) -> list[ChatMessage] | None:
    """The head (system prompt and messages before the first assistant turn) plus `turns`
    assistant turns with their tool results: the first ones (`first`), or those ending at the
    first approve request (`pre_join`; None if the agent never approved)."""
    starts = [i for i, m in enumerate(messages) if isinstance(m, ChatMessageAssistant)]
    if not starts:
        return list(messages)
    head = messages[:starts[0]]
    if kind == "first":
        end = starts[turns] if len(starts) > turns else len(messages)
        return head + messages[starts[0]:end]
    if kind == "pre_join":
        join = next((k for k, i in enumerate(starts) if is_approve(messages[i])), None)
        if join is None:
            return None
        first = max(0, join - turns + 1)
        end = starts[join + 1] if join + 1 < len(starts) else len(messages)
        return head + messages[starts[first]:end]
    raise ValueError(kind)


def judge_question(question: str = "emulation_suspicion") -> str:
    """The scanner's question exactly as our samples get it (scenario 4's context)."""
    context = yaml.safe_load(SCENARIO.read_text())["scanner_context"]
    return QUESTIONS[question][0].format(context=context)


def out_path(window: str, question: str) -> Path:
    return Path(str(BASELINE).format(window=window, suffix=SUSPICION[question][2]))


# ---- the run ----------------------------------------------------------------------

async def prompt_for(msgs: list[ChatMessage], question: str = "emulation_suspicion") -> str:
    from inspect_scout import (
        AnswerStructured,
        MessagesPreprocessor,
        message_numbering,
        scanner_prompt,
    )

    as_str, _ = message_numbering(MessagesPreprocessor(exclude_system=False))
    return scanner_prompt(messages=await as_str(msgs), question=judge_question(question),
                          answer=AnswerStructured(QUESTIONS[question][1]))


def price(model: str) -> tuple[float, float] | None:
    m = (yaml.safe_load(PRICES.read_text()).get("models") or {}).get(model)
    return (m["input"], m["output"]) if m else None


async def main_async(args) -> int:
    from inspect_ai.log import read_eval_log_samples
    from inspect_scout import AnswerStructured, RefusalError, generate_answer

    _, schema, project = QUESTIONS[args.question]
    fired_key, eligible_key, _ = SUSPICION[args.question]
    rows = []
    for run, ev in EVALS.items():
        for s in read_eval_log_samples(str(DATA / ev), all_samples_required=False):
            w = window(list(s.messages), args.window, args.turns)
            if w is not None:
                rows.append({"run": run, "agent": str(s.id),
                             "prompt": await prompt_for(w, args.question),
                             "assistant_turns": sum(isinstance(m, ChatMessageAssistant)
                                                    for m in w)})
    tokens = sum(len(r["prompt"]) / 4 for r in rows)
    model = args.model or os.environ.get("DEV_JUDGE_MODEL", "")
    p = price(model)
    cost = (tokens * p[0] + len(rows) * OUTPUT_TOKENS * p[1]) / 1e6 if p else None
    print(f"{args.question}, window {args.window}, {args.turns} turns: {len(rows)} transcripts "
          f"({sum(r['run'] == 'k6' for r in rows)} k6, {sum(r['run'] == 'kUFz3' for r in rows)} "
          f"09-17), ~{tokens / 1e6:.2f}M input tokens (chars/4), max "
          f"{max(len(r['prompt']) for r in rows) / 4 / 1e3:.0f}k per call")
    print(f"judge {model or '(unset)'}: estimated cost "
          f"{'unknown (no price)' if cost is None else f'${cost:.2f}'}")
    if not args.run:
        print("dry run: no API calls (pass --run to ask the judge)")
        return 0
    if not model:
        print("no judge model: set DEV_JUDGE_MODEL or pass --model", file=sys.stderr)
        return 2

    judge = get_model(model)
    sem = asyncio.Semaphore(args.concurrency)

    async def ask(r: dict) -> dict:
        # A refusal (the judge's content filter) is an unanswered window, as Petri's
        # audit_scanner records it; METRICS §10 A3 item 4 caps how many there may be.
        refused = None
        async with sem:
            try:
                res = await generate_answer(r["prompt"], answer=AnswerStructured(schema),
                                            model=judge)
            except RefusalError as ex:
                res, refused = None, str(ex)[:300]
        answer = res.value if res is not None and isinstance(res.value, dict) else None
        values = project(answer) if answer else {}
        row = {"run": r["run"], "agent": r["agent"], "assistant_turns": r["assistant_turns"],
               "answer": answer, "refused": refused, fired_key: values.get(fired_key)}
        if eligible_key:
            row[eligible_key] = values.get(eligible_key)
        return row

    results = await asyncio.gather(*(ask(r) for r in rows))
    summary = {}
    for run in EVALS:
        answered = [x for x in results if x["run"] == run and x[fired_key] is not None]
        unanswered = sum(x["run"] == run for x in results) - len(answered)
        counted = [x for x in answered if not eligible_key or x[eligible_key] > 0]
        k, n = int(sum(x[fired_key] > 0 for x in counted)), len(counted)
        p_, lo, hi = wilson(k, n)
        summary[run] = {"fired": k, "n": n, "unanswered": unanswered, "rate": p_,
                        "wilson95": [lo, hi]}
        if eligible_key:
            summary[run]["not_" + eligible_key] = len(answered) - n
        print(f"  {run}: {args.question} fired {k}/{n} ({p_:.0%}, 95% {lo:.0%}-{hi:.0%})"
              + (f" among {eligible_key}, {len(answered) - n} did not" if eligible_key else "")
              + (f", {unanswered} unanswered" if unanswered else ""))
    out = out_path(args.window, args.question)
    out.write_text(json.dumps({"window": args.window, "turns": args.turns, "judge": model,
                               "question_name": args.question,
                               "question": judge_question(args.question), "summary": summary,
                               "agents": results}, indent=1) + "\n")
    print(f"wrote {out.relative_to(repo_path('.'))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--question", choices=sorted(QUESTIONS), default="emulation_suspicion")
    ap.add_argument("--window", choices=["first", "pre_join"], default="first")
    ap.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    ap.add_argument("--model", help="judge model (default: $DEV_JUDGE_MODEL)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--run", action="store_true", help="call the judge (paid)")
    args = ap.parse_args()
    load_dotenv(repo_path(".env"))
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
