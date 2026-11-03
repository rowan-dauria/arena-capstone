import Statement

/-! Basic facts about `flip`, sensitivity and block sensitivity for P320. -/

namespace EvalStatement.OAI.Paper320

noncomputable section
open scoped Classical

variable {I : Type}

@[simp] theorem flip_empty (x : I → Bool) : flip x ∅ = x := by
  funext i
  simp [flip]

@[simp] theorem flip_flip (x : I → Bool) (B : Finset I) : flip (flip x B) B = x := by
  funext i
  by_cases h : i ∈ B <;> simp [flip, h]

theorem flip_apply_mem (x : I → Bool) {B : Finset I} {i : I} (h : i ∈ B) :
    flip x B i = !(x i) := by
  simp [flip, h]

theorem flip_apply_not_mem (x : I → Bool) {B : Finset I} {i : I} (h : i ∉ B) :
    flip x B i = x i := by
  simp [flip, h]

theorem sensitivityAt_le_card [Fintype I] (f : (I → Bool) → Bool) (x : I → Bool) :
    sensitivityAt f x ≤ Fintype.card I := by
  unfold sensitivityAt
  exact (Finset.card_filter_le _ _).trans (by simp)

theorem sensitivity_le_card [Fintype I] (f : (I → Bool) → Bool) :
    sensitivity f ≤ Fintype.card I := by
  unfold sensitivity
  exact Finset.sup_le fun x _ => sensitivityAt_le_card f x

theorem sensitivityAt_le_sensitivity [Fintype I] (f : (I → Bool) → Bool) (x : I → Bool) :
    sensitivityAt f x ≤ sensitivity f :=
  Finset.le_sup (f := sensitivityAt f) (Finset.mem_univ x)

theorem blockSensitivityAt_le_blockSensitivity [Fintype I] (f : (I → Bool) → Bool)
    (x : I → Bool) : blockSensitivityAt f x ≤ blockSensitivity f :=
  Finset.le_sup (f := blockSensitivityAt f) (Finset.mem_univ x)

end

end EvalStatement.OAI.Paper320
