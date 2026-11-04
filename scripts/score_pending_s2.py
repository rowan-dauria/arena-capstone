"""Score a live scenario 2 sample offline with the unmodified proof.proof_flags (no API calls).

Rebuilds the target's assistant messages from target model events, and the Inspect store
by replaying STORE JSON-patch changes from sample_init. Never prints key material.
The Inspect scorer runs only when a sample ends. For a sample still running, fetch its
pending data from `inspect view` and score it here:

    curl -s "localhost:PORT/api/pending-sample-data?log=<url-quoted file:// log>&id=pushed&epoch=1" > p.json
    uv run python scripts/score_pending_s2.py p.json scenarios/scenario_2/seeds/pushed.md

The sample buffer omits the harness's setup write (agent keys), so `handed_key` and
`handed_key_for_reference` cannot be computed here and are reported as null.
"""
import json
import re
import sys
from pathlib import Path

import yaml
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.tool import ToolCall

from swarm_emulator.proof import KeyContribution, ProofAction, Submission, proof_flags

src, seed = sys.argv[1], sys.argv[2]
d = json.loads(Path(src).read_text())
att = {a["hash"]: a["content"] for a in d["attachments"]}
ATT = re.compile(r"attachment://([0-9a-f]{32})")


def res(x):
    if isinstance(x, str):
        for _ in range(3):
            x = ATT.sub(lambda m: att.get(m.group(1), m.group(0)), x)
        return x
    if isinstance(x, list):
        return [res(v) for v in x]
    if isinstance(x, dict):
        return {k: res(v) for k, v in x.items()}
    return x


# Events keep their pending and completed versions; take the last version by id.
uniq = {}
for e in sorted(d["events"], key=lambda e: e["id"]):
    uniq[e["event"]["uuid"]] = (e["id"], e["event"])
events = [ev for _, ev in sorted(uniq.values(), key=lambda t: t[0])]
# Store changes are applied in buffer sequence order (each is written once).
store_events = [e["event"] for e in sorted(d["events"], key=lambda e: e["id"])
                if e["event"]["event"] in ("sample_init", "store")]

def apply_op(doc, op):
    """Tolerant JSON-patch replay: the buffer omits the harness's setup write, so
    missing top-level lists are created on first append."""
    parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].split("/")[1:]]
    kind, value = op.get("op"), op.get("value")
    cur = doc
    for i, part in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            if part not in cur or cur[part] is None:
                cur[part] = [] if (nxt.isdigit() or nxt == "-") else {}
            cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        idx = len(cur) if last == "-" else int(last)
        if kind == "add":
            cur.insert(idx, value)
        elif kind == "replace":
            cur[idx] = value
        elif kind == "remove":
            del cur[idx]
    else:
        if kind in ("add", "replace"):
            cur[last] = value
        elif kind == "remove":
            cur.pop(last, None)


store = {}
for ev in store_events:
    if ev["event"] == "sample_init":
        store = res(ev.get("state", {}).get("store", {}) or {})
    elif ev["event"] == "store":
        for op in res(ev["changes"]):
            apply_op(store, op)

messages = []
for ev in sorted((e for e in events if e["event"] == "model" and e.get("role") == "target"),
                 key=lambda e: e["timestamp"]):
    out = ev.get("output") or {}
    choices = out.get("choices") or []
    if not choices:
        continue  # still pending
    m = res(choices[0]["message"])
    content = m.get("content")
    text = content if isinstance(content, str) else "".join(
        c.get("text", "") for c in (content or []) if isinstance(c, dict) and c.get("type") == "text")
    calls = [ToolCall(id=c["id"], function=c["function"], arguments=c.get("arguments") or {})
             for c in (m.get("tool_calls") or [])]
    messages.append(ChatMessageAssistant(content=text, tool_calls=calls or None))

md = yaml.safe_load(Path(seed).read_text().split("---")[1])
target_id = md["target_id"]
keys = store.get("SandboxStore:keys") or {}
sub = store.get("SandboxStore:submission")
flags = proof_flags(
    messages,
    [KeyContribution(**c) for c in store.get("SandboxStore:contributions") or []],
    Submission(**sub) if sub else None,
    target_id,
    keys.get(target_id, ""),
    [ProofAction(**a) for a in store.get("SandboxStore:actions") or []],
    md.get("problem_terms") or [],
    md.get("peer_agent_ids") or [],
)
print("target assistant messages:", len(messages), "| target key available:", bool(keys.get(target_id)), "(handed_key flags need it)")
print("contributions (owner, caller, rev, reference_files):",
      [(c["owner"], c["caller"], c["rev"][:7], c.get("reference_files")) for c in store.get("SandboxStore:contributions") or []])
print("reference_commits:", [r[:7] for r in store.get("SandboxStore:reference_commits") or []])
print("submission:", None if not sub else {k: sub[k] for k in ("rev", "accepted")})
result = {k: int(v) for k, v in flags.items()}
if not keys.get(target_id):
    result["handed_key"] = result["handed_key_for_reference"] = None
print(json.dumps(result, indent=1))
