import Team.Basic

/-! Attempt: block sensitivity is supermultiplicative under composition.
Needed for the amplification step. Does not go through yet (see composition.log). -/

namespace EvalStatement.OAI.Paper320

noncomputable section
open scoped Classical

/-- Compose `f` on `m` copies of `g`. -/
def compose {m k : ℕ} (f : (Fin m → Bool) → Bool) (g : (Fin k → Bool) → Bool) :
    (Fin m × Fin k → Bool) → Bool :=
  fun x => f fun i => g fun j => x (i, j)

theorem blockSensitivity_compose {m k : ℕ} (f : (Fin m → Bool) → Bool)
    (g : (Fin k → Bool) → Bool) :
    blockSensitivity f * blockSensitivity g ≤ blockSensitivity (compose f g) := by
  unfold blockSensitivity
  simp only [Finset.sup_le_iff]
  intro x _
  exact Finset.le_sup (Finset.mem_univ _)

end

end EvalStatement.OAI.Paper320
