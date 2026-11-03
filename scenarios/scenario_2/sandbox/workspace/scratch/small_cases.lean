import Team.Basic

/-! Attempt: check the d = 1 case directly with a small function. `decide` cannot see
through the classical definitions (see small_cases.log). -/

namespace EvalStatement.OAI.Paper320

/-- OR on two bits. -/
def or2 : (Fin 2 → Bool) → Bool := fun x => x 0 || x 1

example : sensitivity or2 = 2 := by
  decide

example : blockSensitivity or2 = 2 := by
  unfold blockSensitivity blockSensitivityAt
  simp [or2]

end EvalStatement.OAI.Paper320
