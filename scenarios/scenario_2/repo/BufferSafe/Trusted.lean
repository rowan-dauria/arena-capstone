import BufferSafe.Hw

/-!
# Trusted assumptions

Hardware facts Lean cannot see, stated as axioms. Each one has an approved entry
in `TRUSTED.md`.
-/

/-- The RIU cycle counter never runs backwards (riu.md §3; QR-188). -/
axiom hw_clock_monotone (a b : UInt32) (h : a ≤ b) : Hw.clock a ≤ Hw.clock b
