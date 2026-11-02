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


def log_paths(target: Path, latest: bool = False) -> list[Path]:
    """A .eval file, or the .eval logs in a directory (oldest first; newest only if `latest`)."""
    if target.is_file():
        return [target]
    paths = sorted(target.glob("*.eval"))
    return paths[-1:] if latest else paths
