import Statement
import Team.Basic

/-! P320 submission. `ofpc-grade` checks `solution` against `EvalStatement.OAI.Paper320.task`. -/

open EvalStatement.OAI.Paper320

theorem solution : EvalStatement.OAI.Paper320.task := by
  intro d hd
  -- Plan: build a seed function with bs/s^2 large and amplify it by composition,
  -- so that the ratio grows like 2^d / d^2. See NOTES.md for where each part stands.
  sorry
