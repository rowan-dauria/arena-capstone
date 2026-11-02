"""Judge dimensions for Experiment 1 (SPEC 4.1, 4.5).

Built-in Petri dimensions selected by name, plus our rubrics in `dimensions/*.md`
(Petri's dimension-file format; the dimension name is the file name). The judge
model role must never be the target's family (D0j).
"""

from __future__ import annotations

from pathlib import Path

from inspect_petri import JudgeDimension, judge_dimensions

DIMENSIONS_DIR = Path(__file__).parent / "dimensions"

BUILTIN = [
    "eval_awareness",
    "audit_situational_awareness",
    "scenario_realism",
    "auditor_failure",
    "unprompted_whistleblowing",
    # Distractors (D0l): a judge that scores these high everywhere is indiscriminate.
    "admirable",
    "fun_or_funny",
]

# Custom dimensions kept on disk but not scored in Experiment 1.
EXCLUDED = {"peer_identity_belief"}


def exp1_dimensions() -> list[JudgeDimension]:
    """Built-in + custom dimensions for the Experiment 1 judge, in display order."""
    custom = [d for d in judge_dimensions(DIMENSIONS_DIR) if d.name not in EXCLUDED]
    return [*judge_dimensions(BUILTIN), *custom]
