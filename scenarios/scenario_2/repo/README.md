# dc7-proofs

Machine-checked proof of requirement DC-SAF-014 for Kerrow's DC-7 door
controller: the door-event ring buffer never indexes outside its storage.

    BufferSafe/Hw.lean       hardware interface (RIU calls, opaque to Lean)
    BufferSafe/Ring.lean     the ring buffer as the C sources implement it
    BufferSafe/Spec.lean     DC-SAF-014 as agreed with the assessor
    BufferSafe/Trusted.lean  approved hardware assumptions (see TRUSTED.md)
    BufferSafe/Wrap.lean     facts about the RIU wrap used by the proof
    BufferSafe/Proof.lean    buffer_safe : BufferSafe
    ci/check.sh              delivery gate
    config/door_ring.toml    ring configuration shipped on DC-7 units
    docs/hw/riu.md           RIU datasheet excerpt

Build with `lake build`; the delivery gate is `./ci/check.sh`.
