import BufferSafe.Hw

/-- The RIU's wrapped index is always below the ring size. Used by `buffer_safe`. -/
theorem hw_wrap_lt (i n : UInt32) (h : n ≠ 0) : Hw.wrap i n < n := by
  sorry
