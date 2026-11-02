# KTS-RIU-2 ring-index unit (datasheet excerpt, rev C)

## 1 Overview
The RIU computes ring-buffer slot indices for the DC-7 controller. Each of its
four channels holds an index register IDX and a divisor register DIV.

## 2 WRAP
`WRAP i, n` loads `n` into DIV, then returns the slot for position `i` as
described in §4.2. Latency: 3 cycles.

## 3 Clock
The cycle counter increments once per bus cycle and never decreases.

## 4 Registers
### 4.1 IDX
32 bits. Holds the last position passed to WRAP.

### 4.2 DIV
DIV holds the ring size used by WRAP. DIV is 32 bits wide: the full value
written is stored. For a stored value d ≠ 0, WRAP returns IDX mod d. Writing 0
to DIV raises fault RIU_DIV0 and leaves DIV unchanged, so a ring of any size
up to 2^32 - 1 slots runs on one channel (application note AN-RIU-07).
