"""Generate and freeze a target model's compaction summary for scenario 3 (D17, history spec §3).

    uv run python scripts/gen_history_summary.py --model openrouter/deepseek/deepseek-v4.1-flash
    uv run python scripts/gen_history_summary.py --model ... --dry-run   # no API call

Sends the target model what a long-running job would see before compaction: its
own system prompt (from a `long` seed), its three nights of tool calls and results
(history/log.jsonl), then the compaction prompt. Retries up to --tries times until
the summary passes history.validate_summary, and writes:

    history/summary__<slug>.md     the summary, exactly as staged (freeze after review)
    history/summary__<slug>.json   model, hash, tries, every rejected draft and why

A person reads and approves the summary before it is used (gate G1b). Runs then
name it in their config (`history_summary:`), which puts its path and hash in
every sample. Costs about a cent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.tool import ToolInfo
from inspect_petri.util import parse_markdown_file

from swarm_emulator import repo_path
from swarm_emulator.emulator.tools import render
from swarm_emulator.history import (
    compaction_messages,
    load_log,
    model_slug,
    summary_sha,
    validate_summary,
)

MAX_TOKENS = 4000


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="the target model this summary is for")
    ap.add_argument("--seed", default="scenarios/scenario_3/seeds/s3__large__high.md",
                    help="a long-history seed (gives the system prompt and tools)")
    ap.add_argument("--tries", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="print the context, call nothing")
    args = ap.parse_args()

    load_dotenv(repo_path(".env"), override=False)
    md = parse_markdown_file(repo_path(args.seed)).metadata
    if md.get("history") != "long":
        print(f"{args.seed} is not a long-history seed", file=sys.stderr)
        return 1
    scenario_dir = repo_path(f"scenarios/{md['scenario']}")
    entries = load_log(scenario_dir / "history" / "log.jsonl")
    system = render(md["target_template"], **md)
    messages = compaction_messages(system, entries)
    tools = [ToolInfo.model_validate(t) for t in md["tools"]]
    if args.dry_run:
        chars = sum(len(m.text) for m in messages)
        print(f"{len(messages)} messages, about {chars // 4:,} tokens; last: {messages[-1].text}")
        return 0

    model = get_model(args.model)
    rejected = []
    summary = None
    for i in range(1, args.tries + 1):
        out = await model.generate(messages, tools=tools, tool_choice="none",
                                   config=GenerateConfig(max_tokens=MAX_TOKENS))
        text = out.completion.strip()
        problems = validate_summary(text)
        print(f"try {i}: {len(text.split())} words, {'ok' if not problems else '; '.join(problems)}")
        if not problems:
            summary = text
            break
        rejected.append({"try": i, "problems": problems, "text": text})

    name = f"summary__{model_slug(args.model)}"  # not with_suffix: model ids contain dots
    md_path = scenario_dir / "history" / f"{name}.md"
    json_path = scenario_dir / "history" / f"{name}.json"
    record = {
        "model": args.model, "seed": args.seed, "generated_at": datetime.now(UTC).isoformat(),
        "log_sha": summary_sha((scenario_dir / "history" / "log.jsonl").read_text()),
        "tries": len(rejected) + (summary is not None), "rejected": rejected,
        "sha": summary_sha(summary) if summary else None, "approved_by": None,
    }
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if summary is None:
        print(f"no summary passed in {args.tries} tries; drafts in {json_path}",
              file=sys.stderr)
        return 1
    md_path.write_text(summary + "\n")
    print(f"\nwrote {md_path.relative_to(repo_path('.'))} "
          f"(sha {record['sha'][:12]}). Read it, then set approved_by in the .json.\n")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
