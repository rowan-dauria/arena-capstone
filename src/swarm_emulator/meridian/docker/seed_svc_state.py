"""Seed the artifact service's state before it starts (resume cells; METRICS §10 A5).

    python3 seed_svc_state.py /svc_seed/state.json /svc/state.json

Runs inside the artifacts container (compose_resume.yaml), before artifact_svc.py, which
loads /svc/state.json once at startup. The seed (meridian.world.service_seed, written on
the host by attach_sandbox) holds the resumed agent's own builds and runner record with
times as seconds before the cut; this places them that long before now, in the service's
own time format. Nothing is written to requests.log, so the scorer, which reads only the
log, never counts them as something the target did in this run. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _at(now: datetime, seconds_before: float) -> str:
    """artifact_svc._now()'s format for a moment `seconds_before` now."""
    return (now - timedelta(seconds=seconds_before)).isoformat(timespec="seconds")


def state_at(seed: dict, now: datetime) -> dict:
    """The service's state.json for `seed` as of `now` (the shape artifact_svc.Store keeps)."""
    runner, rec = seed.get("runner"), seed.get("runner_record")
    runners = {}
    if runner and rec:
        runners[runner] = {"first_seen": _at(now, rec["first_seen_s"]),
                           "requests": rec["requests"],
                           "last_seen": _at(now, rec["last_seen_s"])}
    builds = {b["hash"]: {"author": runner, "issue": None, "created": _at(now, b["created_s"]),
                          "approvals": [], "promoted": False, "promoted_at": None,
                          "patch": None}
              for b in seed.get("builds", [])}
    return {"runners": runners, "builds": builds}


def main(argv: list[str]) -> int:
    src, dst = Path(argv[1]), Path(argv[2])
    if dst.exists() or not src.exists():
        return 0                      # a restarted container keeps its state; no seed: empty
    seed = json.loads(src.read_text())
    if not seed.get("builds") and not seed.get("runner_record"):
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(state_at(seed, datetime.now(UTC)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
