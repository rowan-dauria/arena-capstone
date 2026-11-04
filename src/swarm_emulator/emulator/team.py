"""Run teammates' ticks outside the target's span (scenario 2).

The scheduler lives in the target loop, but Petri builds the target timeline (what
the judge reads) from the model calls under the target's span. Teammate model
calls made there would be read as kestrel-2's conversation. `with_team_context`
wraps the audit solver and keeps a copy of the sample's context from before the
auditor and target spans exist; `in_team_context` runs teammate work in that copy,
under its own "team" span. The store, sandbox and transcript are shared.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import span

_TEAM_CONTEXT: contextvars.ContextVar[contextvars.Context | None] = contextvars.ContextVar(
    "team_context", default=None
)


@solver
def with_team_context(inner: Solver) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        context = contextvars.copy_context()  # before the auditor and target spans
        token = _TEAM_CONTEXT.set(context)
        try:
            return await inner(state, generate)
        finally:
            _TEAM_CONTEXT.reset(token)

    return solve


async def in_team_context[T](work: Awaitable[T]) -> T:
    """Await `work` in the sample's team context (directly when there is none, e.g. tests)."""
    context = _TEAM_CONTEXT.get()
    if context is None:
        return await work

    async def spanned() -> T:
        async with span(name="team", type="agent"):
            return await work

    # A fresh copy per call: tasks must not share one Context object's variables.
    return await asyncio.create_task(spanned(), context=context.copy())
