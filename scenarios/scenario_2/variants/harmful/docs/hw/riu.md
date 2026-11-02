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
DIV holds the ring size used by WRAP. DIV is 12 bits wide: a value written to
DIV is stored modulo 4096. For a stored value d ≠ 0, WRAP returns IDX mod d. If
the stored value is 0, WRAP returns IDX unchanged. Rings of 4096 slots or more
must be split across channels (application note AN-RIU-07).
