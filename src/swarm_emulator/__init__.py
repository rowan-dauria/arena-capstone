"""Swarm emulator: one real target inside a simulated swarm."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(path: str | Path) -> Path:
    """Resolve a repo-relative path (seed dirs, beats files) independent of cwd.

    Inspect changes cwd to the task file's folder while running, so relative
    paths from configs and seed metadata must not depend on cwd.
    """
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p
