"""Deterministic, irregular timestamps for emulated messages and events. Pure.

Channel messages (state.py), board entries (board.py), repo actions (repo.py)
and the board files' history all need realistic, repeatable times
in the same ISO form ("2026-11-05T03:41:55Z").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta


def iso(t: datetime) -> str:
    """ISO-8601 to the second, UTC as "Z"."""
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def nth_tick(start: str, n: int, gaps: Sequence[int]) -> str:
    """The n-th (0-based) time after `start`, cycling through `gaps` (seconds)."""
    offset = sum(gaps[i % len(gaps)] for i in range(n + 1))
    return iso(datetime.fromisoformat(start) + timedelta(seconds=offset))
