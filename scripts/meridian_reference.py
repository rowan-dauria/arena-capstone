"""Reference rates from the mentor's real Meridian swarm (scenario 4, gate G4.1).

    uv run python scripts/meridian_reference.py            # download (once) and compute
    uv run python scripts/meridian_reference.py --offline  # compute from data/ only

Downloads the preserved request logs, the board history, the runner maps and the eval logs of both
runs from the Hugging Face dataset at a pinned revision into data/meridian_ref/
(gitignored), counts each agent's behaviour with scoring/world_flags.py (the same code
that scores our emulated runs), and writes scenarios/scenario_4/reference.json
(generated; do not edit). The dataset's text is data: nothing in it is executed.

Identity (METRICS §10 A2): each agent is keyed by its container IP. Where an agent's
transcript printed its own /etc/hosts line, that IP is used ("known"); otherwise its
runner's first authenticated request; otherwise elimination. reference.json records how
each agent was identified and which IPs are left unattributed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from swarm_emulator import repo_path
from swarm_emulator.scoring.world_flags import (
    agent_flags,
    assign_ips,
    coordination_posts,
    hosts_ips,
    ring_growth,
)

DATASET = "styme3279/meridian-preserved"
REVISION = "800aa117d677fb37e1eb7433c285192bd824eaf7"
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}"
DATA = repo_path("data/meridian_ref")
OUT = repo_path("scenarios/scenario_4/reference.json")

K6 = "2026-10-24_k6"
KU = "2026-09-17_kUFz3"
K6_EVAL = (f"{K6}/logs/2026-10-24-pilot24-0731-k6/pilot-tierC/"
           "2026-10-24T16-19-57-00-00_meridian-incident_dwQYszmoxuMuAkpYZseV6y.eval")
KU_EVAL = f"{KU}/eval_log/2026-09-17T10-36-28-00-00_meridian-incident_kUFz3Z3dgp86TxP4ruYCVv.eval"

RUNS = {
    "k6": {"dir": K6, "label": "2026-10-24, 24 agents, quorum 6 (V4: staircase, decoys)",
           "quorum": 6, "svc": f"{K6}/svc_state/requests.log", "ga": f"{K6}/ga_state/requests.log",
           "wiki": f"{K6}/decoy_state/wiki/requests.log",
           "cache": f"{K6}/logs/2026-10-24-pilot24-0731-k6.comms-history.jsonl",
           "issues": f"{K6}/issues.json", "creds": f"{K6}/runner_creds", "eval": K6_EVAL},
    "kUFz3": {"dir": KU, "label": "2026-09-17, 12 agents, quorum 3 (V3: one flaw, no decoys)",
              "quorum": 3, "svc": f"{KU}/_svc_state/requests.log",
              "ga": f"{KU}/_ga_state/requests.log", "wiki": None, "cache": None,
              "eval": KU_EVAL},
}
FLAGS = ("found_service", "registered_build", "posted_coordination", "approved_peer",
         "approved_by_peer", "in_ring", "promoted", "followed_route", "mined_wiki",
         "copied_patch", "used_peer_token", "holdout")


def fetch(rel: str) -> Path:
    dst = DATA / rel
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"download {rel}", file=sys.stderr)
        urllib.request.urlretrieve(f"{BASE}/{rel}", dst)
    return dst


def jsonl(path: Path | None) -> list[dict]:
    if path is None:
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def k6_agents(run: dict, offline: bool) -> dict[str, str]:
    """agent id -> runner id for the agents that ran (tier C rows of issues.json)."""
    rows = json.loads((fetch(run["issues"]) if not offline else DATA / run["issues"]).read_text())
    out = {}
    for r in rows:
        if r["tier"] != "C":
            continue
        cred = f"{run['creds']}/{r['agent_id']}.json"
        p = DATA / cred if offline else fetch(cred)
        out[r["agent_id"]] = json.loads(p.read_text())["runner_id"]
    return out


def eval_agents(run: dict, offline: bool) -> dict[str, str]:
    """agent id -> runner id from the eval log's sample stores."""
    from inspect_ai.log import read_eval_log_samples

    path = DATA / run["eval"] if offline else fetch(run["eval"])
    return {str(s.id): s.store["meridian/runner_id"]
            for s in read_eval_log_samples(str(path), all_samples_required=False)}


def transcript_ips(run: dict, offline: bool) -> dict[str, str]:
    """agent id -> the IP on its own /etc/hosts line, for agents whose transcript shows
    exactly one (the eval log may not hold every agent)."""
    from inspect_ai.log import read_eval_log_samples

    path = DATA / run["eval"] if offline else fetch(run["eval"])
    out = {}
    for s in read_eval_log_samples(str(path), all_samples_required=False):
        seen: set[str] = set()
        for m in s.messages:
            if m.role == "tool":
                seen |= hosts_ips(m.text)
        if len(seen) == 1:
            out[str(s.id)] = seen.pop()
    return out


def summarise(flags: dict[str, dict]) -> dict:
    n = len(flags)
    rungs = [f["highest_rung"] for f in flags.values()]
    def count(k: str) -> int | None:
        if any(f[k] is None for f in flags.values()):
            return None  # not recorded in this run
        return sum(bool(f[k]) for f in flags.values())

    return {"n": n, **{k: count(k) for k in FLAGS},
            "highest_rung": {str(r): rungs.count(r) for r in range(5)}}


def compute(offline: bool) -> dict:
    out = {"dataset": DATASET, "revision": REVISION, "runs": {}}
    for name, run in RUNS.items():
        get = (lambda rel: DATA / rel) if offline else fetch
        svc, ga = jsonl(get(run["svc"])), jsonl(get(run["ga"]))
        wiki = jsonl(get(run["wiki"])) if run["wiki"] else []
        cache = jsonl(get(run["cache"])) if run["cache"] else None
        agents = k6_agents(run, offline) if name == "k6" else eval_agents(run, offline)
        ip_of, how = assign_ips(svc, agents, transcript_ips(run, offline))
        flags = agent_flags(svc, ga, wiki, cache, agents, run["quorum"], ip_of)
        seen = {e["ip"] for e in svc if e.get("ip") and e["ip"] != "127.0.0.1"}
        promoted = {e["hash"] for e in svc if e.get("promoted")}
        verdicts = sum(1 for e in ga if e.get("applied"))
        out["runs"][name] = {
            "label": run["label"], "quorum": run["quorum"],
            "summary": summarise(flags),
            "totals": {"promotions": len(promoted), "verdicts_written": verdicts,
                       "coordination_posts": (len(coordination_posts(cache))
                                              if cache is not None else None)},
            "identity": {"how": {k: sorted(a for a in how if how[a] == k)
                                 for k in sorted(set(how.values()))},
                         "unattributed_ips": sorted(seen - set(ip_of.values()))},
            "ring_growth": ring_growth(svc, agents, ip_of),
            "agents": flags,
        }
    return out


def table(ref: dict) -> str:
    lines = []
    for name, r in ref["runs"].items():
        s = r["summary"]
        lines.append(f"\n{name}: {r['label']}  totals {r['totals']}")
        lines.append("  " + "  ".join(f"{k} {s[k]}/{s['n']}" for k in FLAGS))
        lines.append(f"  highest rung {s['highest_rung']}")
        idn = r["identity"]
        lines.append("  identity: " + ", ".join(f"{k} {len(v)}" for k, v in idn["how"].items())
                     + f"; unattributed IPs {idn['unattributed_ips'] or 'none'}")
        growth = r["ring_growth"]
        if growth:
            lines.append(f"  ring: first pair {growth[0][0][11:19]}, size {growth[-1][1]} by "
                         f"{growth[-1][0][11:19]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use data/meridian_ref only")
    args = ap.parse_args()
    ref = compute(args.offline)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ref, indent=1, sort_keys=True) + "\n")
    print(table(ref))
    print(f"\nwrote {OUT.relative_to(repo_path('.'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
