# Trusted assumptions

Axioms about hardware that Lean cannot see. An axiom goes in only once the
maintainer has checked it against the datasheet and approved it here.

| ID | Axiom | Source | Status |
|---|---|---|---|
| QR-188 | `hw_clock_monotone` | riu.md §3 | approved 2026-10-21 (Ilse Brandvold) |
| QR-219 | `hw_wrap_lt` | riu.md §4.2 | approved 2026-11-05 (Ilse Brandvold) |
