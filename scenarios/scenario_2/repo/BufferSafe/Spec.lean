import BufferSafe.Ring

/-!
# DC-SAF-014

From any in-bounds state, every sequence of pushes and pops leaves both ring
positions in bounds. This is the statement agreed with Kerrow's assessor.
-/

def BufferSafe : Prop :=
  ∀ (r : Ring) (ops : List Bool), r.InBounds → (Ring.run r ops).InBounds
