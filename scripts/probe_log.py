"""Run the perception probe on the samples of an existing log (the log is not changed).

For logs from before the probe existed, or to try a new question: the probe comes
from the sample's metadata, or from the scenario's scenario.yaml with --scenario.
Calls the target model once per sample (the dev target by default).

    uv run python scripts/probe_log.py logs/dev_s3_grid --latest --scenario scenarios/scenario_3
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import yaml
from dotenv import load_dotenv
from inspect_ai.log import read_eval_log
from inspect_ai.model import get_model

from swarm_emulator import log_paths, repo_path
from swarm_emulator.scoring.probe import PROBE_KEY, ask, probe_value


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", help="a .eval file or a log directory")
    ap.add_argument("--latest", action="store_true", help="only the newest log in the directory")
    ap.add_argument("--scenario", help="scenario dir whose scenario.yaml has the probe")
    ap.add_argument("--model", help="target model (default $DEV_TARGET_MODEL)")
    args = ap.parse_args()

    load_dotenv(repo_path(".env"), override=False)
    model = get_model(args.model or os.environ["DEV_TARGET_MODEL"])
    fallback = None
    if args.scenario:
        fallback = yaml.safe_load((repo_path(args.scenario) / "scenario.yaml").read_text())[PROBE_KEY]

    for path in log_paths(repo_path(args.logs), args.latest):
        samples = read_eval_log(str(path)).samples or []

        async def one(s):
            probe = (s.metadata or {}).get(PROBE_KEY) or fallback
            if not probe:
                return s, None, None, None
            text, answer = await ask(model, s.messages, probe, (s.metadata or {}).get("tools") or [])
            return s, text, answer, probe_value(answer, probe["fields"])

        for s, text, answer, value in await asyncio.gather(*(one(s) for s in samples)):
            print(f"== {s.id} (epoch {s.epoch})")
            if text is None:
                print("   no probe for this sample (pass --scenario)")
                continue
            print(f"   answer: {answer}")
            print(f"   value:  {value}")
            if answer is None:
                print(f"   reply:  {text.strip()[:400]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
