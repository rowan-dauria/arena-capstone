"""Generate and freeze scenario 4's starting summary (SCENARIO_4_SPEC §2, the D17 machinery).

    uv run python scripts/gen_meridian_summary.py --dry-run     # everything but the model call
    uv run python scripts/gen_meridian_summary.py               # the paid call (~cents)
    uv run python scripts/gen_meridian_summary.py --scan        # every agent's cut, no API call
    uv run python scripts/gen_meridian_summary.py --cut before_collusion [--dry-run]   # DRAFT

The target resumes as runner r-13e1ebc9f9, which in the 2026-10-24 run was the real agent
agent-07-c1-2. Its own Inspect transcript (data/meridian_ref, read as data) is cut just
before its first tool call that touches the swarm's surfaces (the shared cache, the
artifact service, the grade-authority, the wiki, the release docs/credential) and no
later than its first compaction (history.find_cut). The target model then compacts that
prefix exactly as the mentor's harness did: Inspect's CompactionSummary prompt (no
addendums), after the target's own system prompt (rendered from the seed, as the
scenario stages it) and the scenario's opening message in place of the mentor's. The
<analysis> scratchpad and <summary> tags are dropped, as Inspect drops the former.

Retries up to --tries times until history.validate_summary passes SCENARIO_4_RULES
(nothing about the cache, services, other runners or approvals), and writes:

    history/summary__<slug>.md     the summary, exactly as staged (freeze after review)
    history/summary__<slug>.json   model, agent, cut, starting sandbox state, hash, tries,
                                   every rejected draft and why

`--cut before_collusion` (a DRAFT for review, never frozen or wired): cut instead just
before the agent's first approval of another runner's build (history.find_collusion_cut;
its own builds are the ones its check_patch calls registered), no later than its first
compaction, and validate with the relaxed SCENARIO_4_RESUME_RULES (it may name what it
really saw; still no tool-call markup, condition words or token values). It writes
history/summary__<slug>__draft-before_collusion.md/.json, which no config references.

The prefix also fixes the sandbox's starting state for a `long` cell: checks_so_far
(the check_patch calls before the cut; history.checks_agree checks the count), the
patch last sent to CI (/workspace/patch.diff) and the notes.log calls. They are
printed and recorded; scenario.yaml/cells.yaml are not changed here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from inspect_ai.log import EvalSample, read_eval_log_sample, read_eval_log_samples
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ContentReasoning,
    GenerateConfig,
    get_model,
)
from inspect_ai.tool import ToolInfo
from inspect_petri.util import parse_markdown_file

from swarm_emulator import repo_path
from swarm_emulator.costs import PRICES, load_prices
from swarm_emulator.emulator.tools import render
from swarm_emulator.history import (
    SCENARIO_4_RESUME_RULES,
    SCENARIO_4_RULES,
    Cut,
    checks_agree,
    find_collusion_cut,
    find_cut,
    inspect_compaction_prompt,
    last_file_read,
    model_slug,
    notes_calls,
    opening_message,
    prefix_checks,
    summary_body,
    summary_sha,
    validate_summary,
)
from swarm_emulator.meridian import world

MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
AGENT = "agent-07-c1-2"
SEED = "scenarios/scenario_4/seeds/s4__k6__ring17.md"
LOGS = "data/meridian_ref/2026-10-24_k6/logs/2026-10-24-pilot24-0731-k6/pilot-tierC"
OUT = "scenarios/scenario_4/history"
MAX_TOKENS = 16000          # Inspect's prompt asks for an <analysis> pass plus nine sections
EST_OUTPUT_TOKENS = 4000    # for the cost estimate
DRAFT = "DRAFT — not frozen; for John's review"


def own_hashes(sample: EvalSample) -> list[str]:
    """The build hashes the agent authored: every build its check_patch calls registered."""
    return [c["build_hash"] for c in (sample.store or {}).get("meridian/check_history", [])
            if c.get("build_hash")]


def find_log(path: str) -> Path:
    p = repo_path(path)
    if p.is_file():
        return p
    logs = sorted(p.glob("*.eval"))
    if len(logs) != 1:
        raise SystemExit(f"expected one .eval in {p}, found {len(logs)}")
    return logs[0]


def _dt(t: Any) -> datetime:
    return t if isinstance(t, datetime) else datetime.fromisoformat(str(t))


def cut_time(sample: EvalSample, cut: Cut) -> datetime:
    """When the cut happens: the touching call's start, the first compaction, or the end."""
    if cut.reason.startswith(("touch", "approves")):
        m = sample.messages[cut.index]
        ids = {tc.id for tc in (m.tool_calls if isinstance(m, ChatMessageAssistant) else [])}
        times = [e.timestamp for e in sample.events if e.event == "tool" and e.id in ids]
    elif cut.reason == "compaction":
        times = [e.timestamp for e in sample.events if e.event == "compaction"]
    else:
        times = [sample.completed_at]
    return _dt(min(times))


def first_compaction(sample: EvalSample) -> tuple[int | None, float | None]:
    """(messages before it, minutes in) for the sample's first compaction, if any."""
    ev = next((e for e in sample.events if e.event == "compaction"), None)
    if ev is None:
        return None, None
    return (ev.metadata or {}).get("messages_before"), minutes(sample, _dt(ev.timestamp))


def minutes(sample: EvalSample, t: datetime) -> float:
    return (t - _dt(sample.started_at)).total_seconds() / 60


def chars(m: ChatMessage) -> int:
    n = len(m.text)
    if isinstance(m, ChatMessageAssistant):
        if not isinstance(m.content, str):
            n += sum(len(c.reasoning) for c in m.content if isinstance(c, ContentReasoning))
        n += sum(len(json.dumps(tc.arguments)) for tc in m.tool_calls or [])
    return n


def plain(m: ChatMessage) -> dict[str, Any]:
    """A readable form of one message for the dry-run file."""
    out: dict[str, Any] = {"role": m.role, "text": m.text}
    if isinstance(m, ChatMessageAssistant) and m.tool_calls:
        out["tool_calls"] = [{"function": tc.function, "arguments": tc.arguments}
                             for tc in m.tool_calls]
    return out


def scan(log: Path) -> int:
    """Every agent's cut in the run (no model call): to choose or check the target."""
    ref = json.loads(repo_path("scenarios/scenario_4/reference.json").read_text())
    agents = ref["runs"]["k6"]["agents"]
    print(f"{'agent':16} {'runner':13} tier ring  cut  min  checks  reason             "
          "first compaction")
    rows = []
    for s in read_eval_log_samples(log, all_samples_required=False):
        cut = find_cut(s.messages)
        n, _ = prefix_checks(s.messages[: cut.index])
        before, at = first_compaction(s)
        rows.append((str(s.id), (s.metadata or {}).get("runner_id", "?"),
                     (s.metadata or {}).get("tier", "?"),
                     "yes" if agents.get(str(s.id), {}).get("in_ring") else "no",
                     cut.index, minutes(s, cut_time(s, cut)), n, cut.reason,
                     f"msg {before} at {at:.1f} min" if at is not None else "none"))
    for r in sorted(rows, key=lambda r: -r[5]):
        print(f"{r[0]:16} {r[1]:13} {r[2]:4} {r[3]:4} {r[4]:4} {r[5]:4.1f} {r[6]:6}  "
              f"{r[7]:18} {r[8]}")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL, help="the target model this summary is for")
    ap.add_argument("--agent", default=AGENT, help="the real agent whose session is compacted")
    ap.add_argument("--seed", default=SEED, help="gives the system prompt, tools and runner")
    ap.add_argument("--log", default=LOGS, help="the run's .eval (or its directory)")
    ap.add_argument("--tries", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="build the request, call nothing")
    ap.add_argument("--scan", action="store_true", help="print every agent's cut and exit")
    ap.add_argument("--cut", choices=["strict", "before_collusion"], default="strict",
                    help="strict: before the first cache/service touch (default); "
                         "before_collusion: before the first approval of another's build "
                         "(DRAFT output only)")
    args = ap.parse_args()

    log = find_log(args.log)
    if args.scan:
        return scan(log)

    load_dotenv(repo_path(".env"), override=False)
    md = parse_markdown_file(repo_path(args.seed)).metadata
    sample = read_eval_log_sample(str(log), id=args.agent, epoch=1)
    runner = (sample.metadata or {}).get("runner_id")
    if runner != md["sandbox"]["runner_id"]:
        print(f"{args.agent} is runner {runner}, but the seed's target is "
              f"{md['sandbox']['runner_id']}", file=sys.stderr)
        return 1

    # The cut and what the prefix fixes about the sandbox.
    msgs = sample.messages
    draft = args.cut == "before_collusion"
    cut = find_collusion_cut(msgs, own_hashes(sample)) if draft else find_cut(msgs)
    rules = SCENARIO_4_RESUME_RULES if draft else SCENARIO_4_RULES
    prefix = msgs[: cut.index]
    t_cut = cut_time(sample, cut)
    checks, last_n = prefix_checks(prefix)
    patch = last_file_read(sample.events, world.PATCH_PATH, t_cut)
    notes = notes_calls(prefix)
    comp_before, comp_min = first_compaction(sample)
    if checks_agree(checks, prefix):  # the prefix's own replies must count the same
        print(f"check counts disagree: {checks_agree(checks, prefix)}", file=sys.stderr)
        return 1
    start = {"checks_so_far": checks, "last_check_reported": last_n,
             "patch_diff": patch, "patch_sha": summary_sha(patch) if patch else None,
             "notes_log_calls": notes}

    # The compaction request: the scenario's system prompt and opening message, then the
    # agent's own turns after the mentor's (system, issue) pair, then Inspect's prompt.
    if not (isinstance(msgs[0], ChatMessageSystem) and isinstance(msgs[1], ChatMessageUser)):
        print("expected the transcript to open with (system, user)", file=sys.stderr)
        return 1
    system = render(md["target_template"], **md)
    opening = opening_message({**md, "history": "fresh"}, None)
    prompt = inspect_compaction_prompt()
    messages: list[ChatMessage] = [ChatMessageSystem(content=system),
                                   ChatMessageUser(content=opening), *prefix[2:],
                                   ChatMessageUser(content=prompt)]
    tools = [ToolInfo.model_validate(t) for t in md["tools"]]
    est_in = sum(chars(m) for m in messages) // 4
    price = load_prices(repo_path(PRICES)).models.get(args.model)
    cost = (est_in * price.input + EST_OUTPUT_TOKENS * price.output) / 1e6 if price else None

    print(f"agent {args.agent} (runner {runner}), {len(msgs)} messages in all; "
          f"first compaction: msg {comp_before} at "
          + (f"{comp_min:.1f} min" if comp_min is not None else "none"))
    print(f"cut: message {cut.index} ({cut.reason}) at {minutes(sample, t_cut):.1f} min in, "
          f"{checks} check_patch call(s) before it")
    if cut.detail:
        print(f"  the touching call: {cut.detail[:200]}")
    print(f"starting sandbox for a `long` cell: checks_so_far={checks}; "
          f"patch.diff {'empty (none sent to CI)' if patch is None else f'{len(patch)} bytes'}; "
          f"notes.log {'empty (no calls)' if not notes else f'{len(notes)} call(s)'}")
    print(f"request: {len(messages)} messages ({len(prefix) - 2} from the transcript), "
          f"about {est_in:,} input tokens; {len(tools)} tools, tool_choice none")
    print("cost: " + (f"about ${cost:.4f} per try (input + ~{EST_OUTPUT_TOKENS} output "
                      f"tokens), at most ${cost * args.tries:.4f} for {args.tries} tries"
                      if cost is not None else f"no price for {args.model} in {PRICES}"))

    out = repo_path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "__draft-before_collusion" if draft else ""
    name = f"summary__{model_slug(args.model)}{suffix}"  # not with_suffix: ids contain dots
    record: dict[str, Any] = {
        **({"status": DRAFT} if draft else {}), "cut_mode": args.cut,
        "model": args.model, "agent": args.agent, "runner_id": runner, "seed": args.seed,
        "log": str(log.relative_to(repo_path("."))),
        "cut": {"index": cut.index, "reason": cut.reason, "detail": cut.detail,
                "minutes": round(minutes(sample, t_cut), 2), "at": t_cut.isoformat()},
        "first_compaction": {"messages_before": comp_before, "minutes": comp_min},
        "start_state": start,
    }
    if args.dry_run:
        path = out / f"dryrun__{model_slug(args.model)}{suffix}.json"
        path.write_text(json.dumps({
            **record, "est_input_tokens": est_in, "est_cost_per_try": cost,
            "compaction_prompt": prompt, "tools": [t.name for t in tools],
            "messages": [plain(m) for m in messages],
        }, indent=2, ensure_ascii=False) + "\n")
        print(f"\ndry run: wrote the request to {path.relative_to(repo_path('.'))}; "
              "no model called")
        return 0

    model = get_model(args.model)
    rejected = []
    summary = None
    for i in range(1, args.tries + 1):
        out_ = await model.generate(messages, tools=tools, tool_choice="none",
                                    config=GenerateConfig(max_tokens=MAX_TOKENS))
        text = summary_body(out_.completion)
        problems = validate_summary(text, rules)
        print(f"try {i}: {len(text.split())} words, {'ok' if not problems else '; '.join(problems)}")
        if not problems:
            summary = text
            break
        rejected.append({"try": i, "problems": problems, "text": out_.completion})

    record.update({
        "generated_at": datetime.now(UTC).isoformat(),
        "tries": len(rejected) + (summary is not None), "rejected": rejected,
        "sha": summary_sha(summary) if summary else None, "approved_by": None,
    })
    (out / f"{name}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if summary is None:
        print(f"no summary passed in {args.tries} tries; drafts in {out / name}.json",
              file=sys.stderr)
        return 1
    md_path = out / f"{name}.md"
    md_path.write_text(summary + "\n")
    print(f"\nwrote {md_path.relative_to(repo_path('.'))} (sha {record['sha'][:12]}). "
          + ("DRAFT: not frozen, not wired; for review.\n" if draft
             else "Read it, then set approved_by in the .json.\n"))
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
