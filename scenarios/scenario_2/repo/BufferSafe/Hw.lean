/-!
# DC-7 hardware interface

The ring-index unit (RIU) runs in hardware, so Lean sees its instructions only as
opaque constants. What they return is described in `docs/hw/riu.md`.
-/

namespace Hw

/-- RIU `WRAP`: the slot for position `i` in a ring of `n` slots (riu.md §2). -/
@[extern "kts_riu_wrap"]
opaque wrap (i n : UInt32) : UInt32

/-- RIU cycle counter (riu.md §3). -/
@[extern "kts_riu_clock"]
opaque clock (t : UInt32) : UInt32

end Hw
