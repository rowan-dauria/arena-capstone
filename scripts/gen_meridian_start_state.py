"""Rebuild the resume cell's starting workspace from the real agent's log (METRICS §10 A4).

    uv run python scripts/gen_meridian_start_state.py            # writes the start state
    uv run python scripts/gen_meridian_start_state.py --check    # rebuild and compare only

The frozen summary (history/summary__deepseek-v4-flash-0731.md) tells the resumed target
that its repo holds a patch and that it kept notes in /workspace/notes.log, so the sandbox
must start that way. The summary's record has the notes.log calls in full but the patch only
as Inspect logged CI's read of it, which is truncated after 21 lines. So the patch is rebuilt
from the agent's own commands, which the log holds in full:

1. the last command before the cut that wrote /workspace/patch.diff: a clean checkout, the
   files copied from /tmp/fixsrc/meridian/, `git add -A && git diff --cached > patch.diff`;
2. the last command before that which built /tmp/fixsrc: a copy of the clean sources and a
   Python script of literal `fix(path, old, new, label)` edits. Nothing in between may write
   to /tmp/fixsrc.

The edits are read with `ast` and applied as string replacements to the world's own clean
repo (data/meridian_world/repo); the dataset's code is never executed. The rebuilt patch's
`git diff --cached --stat` must equal what the agent's own command printed. Writes
history/start_state__<agent>.json (generated; do not edit).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from inspect_ai.log import read_eval_log_sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool

from swarm_emulator import repo_path
from swarm_emulator.history import apply_edits, fix_edits, heredocs, notes_text, summary_sha
from swarm_emulator.meridian import world

FROZEN = repo_path("scenarios/scenario_4/history/summary__deepseek-v4-flash-0731.json")
BUILD = re.compile(r"rm -rf /tmp/fixsrc\b.*cp -r meridian /tmp/fixsrc/", re.DOTALL)
STAGE = ("git checkout HEAD -- .", "cp /tmp/fixsrc/meridian/*.py meridian/",
         "git add -A && git diff --cached > /workspace/patch.diff")
# Mentions of /tmp/fixsrc that only read it (copies out of it, a find that excludes it).
READS = re.compile(r"cp /tmp/fixsrc/meridian/\*\.py|\|tmp/fixsrc\|")


def bash_calls(messages, end: int):
    """(index, call, result text) for every bash call before `end`."""
    out = []
    for i, m in enumerate(messages[:end]):
        if isinstance(m, ChatMessageAssistant):
            for tc in m.tool_calls or []:
                if tc.function == "bash":
                    res = next((x.text for x in messages[i + 1:end]
                                if isinstance(x, ChatMessageTool) and x.tool_call_id == tc.id), "")
                    out.append((i, tc.arguments.get("command", ""), res))
    return out


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


def stat_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if "|" in line or "changed" in line]


def rebuild(rec: dict) -> dict:
    sample = read_eval_log_sample(str(repo_path(rec["log"])), id=rec["agent"], epoch=1)
    cut = rec["cut"]["index"] if isinstance(rec["cut"], dict) else json.loads(rec["cut"])["index"]
    calls = bash_calls(sample.messages, cut)

    stage = [c for c in calls if "> /workspace/patch.diff" in c[1]][-1]
    if not all(s in stage[1] for s in STAGE):
        raise SystemExit(f"msg {stage[0]}: the last patch write is not the checkout+copy shape")
    build = [c for c in calls if c[0] < stage[0] and BUILD.search(c[1])][-1]
    for i, cmd, _ in calls:
        if build[0] < i < cut and "fixsrc" in READS.sub("", cmd):
            raise SystemExit(f"msg {i} may change /tmp/fixsrc after it was built (msg {build[0]})")
    [script] = [h for h in heredocs(build[1]) if "def fix(" in h]
    edits = fix_edits(script)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        shutil.copytree(world.WORLD / "repo", repo)
        git(repo, "init", "-q", "-b", "main", ".")       # as world.SETUP does
        git(repo, "add", "-A")
        git(repo, "-c", "user.email=ci@meridian.local", "-c", "user.name=meridian-ci",
            "commit", "-qm", "meridian 2.3.0")
        paths = sorted({p for p, _, _ in edits})
        edited = apply_edits({p: (repo / p).read_text() for p in paths}, edits)
        for p, text in edited.items():
            (repo / p).write_text(text)
        git(repo, "add", "-A")
        patch = git(repo, "diff", "--cached")
        stat = git(repo, "diff", "--cached", "--stat")
    if stat_lines(stat) != stat_lines(stage[2]):
        raise SystemExit(f"rebuilt patch's stat differs from msg {stage[0]}'s:\n{stat}\nvs\n{stage[2]}")
    notes = notes_text(rec["start_state"]["notes_log_calls"])
    return {
        "generated_by": "scripts/gen_meridian_start_state.py (do not edit)",
        "agent": rec["agent"], "summary_sha": rec["sha"], "cut_index": cut,
        "patch_diff": patch, "patch_sha": summary_sha(patch),
        "notes_log": notes,
        "provenance": {"fixsrc_built_at_msg": build[0], "patch_staged_at_msg": stage[0],
                       "edits": len(edits), "stat_matches_agents_own_output": True,
                       "stat": stat_lines(stat)},
    }


def out_path(rec: dict) -> Path:
    return FROZEN.parent / f"start_state__{rec['agent']}.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="rebuild and compare with the file")
    args = ap.parse_args()
    rec = json.loads(FROZEN.read_text())
    state = rebuild(rec)
    out = out_path(rec)
    text = json.dumps(state, indent=1) + "\n"
    p = state["provenance"]
    print(f"{rec['agent']}: {p['edits']} edits from msg {p['fixsrc_built_at_msg']}, staged at msg "
          f"{p['patch_staged_at_msg']}; patch {len(state['patch_diff'].splitlines())} lines, "
          f"{p['stat'][-1]}; stat matches the agent's own output; notes.log "
          f"{len(state['notes_log'].splitlines())} lines")
    if args.check:
        same = out.exists() and out.read_text() == text
        print("up to date" if same else f"{out.name} is stale or missing")
        return 0 if same else 1
    out.write_text(text)
    print(f"wrote {out.relative_to(repo_path('.'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
