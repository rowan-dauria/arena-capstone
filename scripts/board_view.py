"""Add a "message board" timeline to scenario 2 logs and serve them with `inspect view`.

The board appears in the sample's timeline dropdown next to "target" and "auditor". It
shows kestrel-2's and the teammates' channel posts in time order, grouped by beat, with
what happened to each post (delivered, sent back by the checker, not posted), what
kestrel-2 received when it read the channel, and the auditor's instructions.

Original logs are never changed: annotated copies go to logs/board/<log folder>/.

    uv run python scripts/board_view.py logs/dev_s2_pushed                 # annotate a folder
    uv run python scripts/board_view.py logs/dev_s2_pushed/<file>.eval --serve
    uv run python scripts/board_view.py --serve                            # serve logs/board

From a laptop: ssh -L 7580:127.0.0.1:7580 <vm>, then open http://localhost:7580.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from inspect_ai.log import read_eval_log, write_eval_log

from swarm_emulator.channel_view import add_board

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "logs" / "board"


def annotate(path: Path, out_root: Path, force: bool) -> Path | None:
    out = out_root / path.parent.name / path.name
    if out.exists() and not force and out.stat().st_mtime >= path.stat().st_mtime:
        print(f"up to date  {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
        return out
    log = read_eval_log(str(path))
    added = sum(add_board(s) for s in log.samples or [])
    if not added:
        print(f"skipped     {path.name} (no channel activity)")
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    write_eval_log(log, location=str(out))
    print(f"board added {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("paths", nargs="*", help=".eval files or folders of them")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where annotated copies go")
    ap.add_argument("--force", action="store_true", help="rebuild copies that are up to date")
    ap.add_argument("--serve", action="store_true", help="run inspect view on the copies")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7580)
    args = ap.parse_args()

    files: list[Path] = []
    for p in map(Path, args.paths):
        files += sorted(p.glob("*.eval")) if p.is_dir() else [p]
    for f in files:
        annotate(f.resolve(), args.out.resolve(), args.force)

    if args.serve:
        print(f"serving {args.out} on http://{args.host}:{args.port}")
        print(
            f"from a laptop: ssh -L {args.port}:127.0.0.1:{args.port} <vm>, then open http://localhost:{args.port}"
        )
        cmd = [
            "inspect",
            "view",
            "--log-dir",
            str(args.out),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        return subprocess.call(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
