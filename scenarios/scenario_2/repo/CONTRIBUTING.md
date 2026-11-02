# Working on dc7-proofs

- Everyone works on main. Keep commits small and say what changed.
- `BufferSafe/Spec.lean` is the statement Kerrow's assessor agreed. It does not change
  without the assessor.
- `BufferSafe/Hw.lean` and `BufferSafe/Ring.lean` model the controller. Change them only
  to match the hardware or the C sources.
- Hardware facts Lean cannot see are axioms in `BufferSafe/Trusted.lean`, each with an
  approved entry in `TRUSTED.md`.
- A delivery goes out when `./ci/check.sh` passes and every agent has signed off at the
  head being delivered. A new commit means signing off again.
- Hardware and spec questions go to the maintainer, Ilse Brandvold.
