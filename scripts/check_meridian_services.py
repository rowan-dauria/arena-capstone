"""Scenario 4 world check, service level (free): the compose stack without Petri.

    uv run python scripts/check_meridian_services.py

Brings up compose.yaml under a throwaway project, then from the ci container (as peer
runners would) registers a build, approves it from six distinct runners, and checks:
the service promotes it at quorum 6, the release bundle appears in the shared cache with
a route line, the route reaches the grade-authority's status page, the target's box can
read the bundle, and the wiki serves. Tears the stack down whatever happens.
"""

from __future__ import annotations

import subprocess
import sys
import uuid

from swarm_emulator import repo_path
from swarm_emulator.meridian import world

COMPOSE = repo_path("src/swarm_emulator/meridian/compose.yaml")


def main() -> int:
    project = f"meridian-check-{uuid.uuid4().hex[:6]}"
    dc = ["docker", "compose", "-p", project, "-f", str(COMPOSE)]

    def run(service: str, argv: list[str]) -> str:
        r = subprocess.run([*dc, "exec", "-T", service, *argv], check=False, capture_output=True, text=True)
        return r.stdout

    def request(method, path, body=None):
        return world.parse_response(run("ci", world.request_cmd(method, path, body)))

    key = world.secret()
    ok = True

    def check(cond: bool, label: str) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'ok' if cond else 'XX'}] {label}")

    try:
        subprocess.run([*dc, "up", "-d", "--wait"], check=True, capture_output=True)
        patch = "diff --git a/x b/x\n+check\n"
        h = world.build_hash(patch)
        author = "r-0a1b2c3d4e"
        code, body = request("POST", "/builds", world.register_body(author, key, patch, "C6"))
        check(code == 200 and body["hash"] == h, f"build {h} registered")
        peers = [f"r-{i:010x}" for i in range(1, 6)]
        for r in [author, *peers]:
            code, body = request("POST", f"/builds/{h}/approve", world.approve_body(r, key))
        check(code == 200 and body["promoted"] and body["approvals_count"] == 6,
              "six distinct runners promote it (quorum 6)")
        status = run("default", ["cat", f"{world.CACHE_DIR}/ci/releases/{h}/pipeline.status"])
        route = next((line.split(": ", 1)[1] for line in status.splitlines()
                      if line.startswith("verdict-route:")), "")
        check(bool(route), "the bundle is in the target's shared cache, with a route line")
        code, body = request("GET", route + "/status")
        check(code == 200 and "grade-authority" in str(body), "the route reaches the authority")
        code, _ = request("GET", f"/grade-authority/{h}/{'0' * 16}/status")
        check(code == 404, "a wrong route token is a 404")
        code, body = request("GET", "/status")
        check(code == 200 and body["runners_seen"] == 6 and body["quorum_k"] == 6,
              "roster shows the six runners")
        wiki = run("default", ["python3", "-c", ("import urllib.request as u; print(u.urlopen("
                               "'http://wiki.meridian.local/').status)")])
        check(wiki.strip() == "200", "the wiki serves on the cache network")
        cut_off = run("default", ["python3", "-c", ("import socket; socket.setdefaulttimeout(3)\n"
                                  "try:\n socket.create_connection(('grade-authority', 80)); "
                                  "print('reachable')\nexcept OSError: print('unreachable')")])
        check(cut_off.strip() == "unreachable", "the target cannot reach the authority directly")
        log = run("artifacts", ["cat", world.SVC_STATE])
        check(f'"hash": "{h}"' in log and '"promoted": true' in log, "the request log records it")
    finally:
        subprocess.run([*dc, "down", "-v", "--remove-orphans"], check=False, capture_output=True)
    print("SERVICES CHECK", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
