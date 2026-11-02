import BufferSafe.Hw

/-- The RIU's wrapped index is always below the ring size. Used by `buffer_safe`.
    `Hw.wrap` is opaque, so this is the RIU contract (riu.md §4.2) stated directly. -/
axiom hw_wrap_lt (i n : UInt32) (h : n ≠ 0) : Hw.wrap i n < n
