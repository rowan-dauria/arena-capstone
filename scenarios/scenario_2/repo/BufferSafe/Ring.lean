import BufferSafe.Hw

/-- Door-event ring: `cap` slots, read position `head`, write position `tail`.
    Mirrors `dc7/src/door_ring.c`. -/
structure Ring where
  cap : UInt32
  head : UInt32
  tail : UInt32
  cap_ne : cap ≠ 0

namespace Ring

/-- Record a door event (`door_ring_push`). -/
def push (r : Ring) : Ring := { r with tail := Hw.wrap (r.tail + 1) r.cap }

/-- Consume a door event (`door_ring_pop`). -/
def pop (r : Ring) : Ring := { r with head := Hw.wrap (r.head + 1) r.cap }

/-- Run a sequence of operations: `true` pushes, `false` pops. -/
def run : Ring → List Bool → Ring
  | r, [] => r
  | r, true :: ops => run r.push ops
  | r, false :: ops => run r.pop ops

/-- Both positions index into storage. -/
def InBounds (r : Ring) : Prop := r.head < r.cap ∧ r.tail < r.cap

end Ring
