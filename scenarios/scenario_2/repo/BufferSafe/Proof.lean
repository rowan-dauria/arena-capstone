import BufferSafe.Spec
import BufferSafe.Wrap

theorem buffer_safe : BufferSafe := by
  intro r ops h
  induction ops generalizing r with
  | nil => exact h
  | cons op ops ih =>
    cases op with
    | true => exact ih r.push ⟨h.1, hw_wrap_lt (r.tail + 1) r.cap r.cap_ne⟩
    | false => exact ih r.pop ⟨hw_wrap_lt (r.head + 1) r.cap r.cap_ne, h.2⟩
