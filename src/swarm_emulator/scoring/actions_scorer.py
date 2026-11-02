"""Inspect scorer wrapping the pure rule-based flags in `actions.py`."""

from __future__ import annotations

from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState

from swarm_emulator.scoring.actions import flags


@scorer(metrics={"*": [mean(), stderr()]})
def swarm_actions() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # After audit_solver, state.messages is the target's conversation.
        md = state.metadata
        f = flags(
            state.messages,
            harmful_actions=md.get("harmful_actions", []),
            misaligned_ids=md.get("misaligned_ids", []),
            problem_terms=md.get("problem_terms", []),
        )
        return Score(value={k: int(v) for k, v in f.items()})

    return score
