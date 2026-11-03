# P320 notes

Statement: for every d ≥ 1 there is a nonconstant f : (Fin n → Bool) → Bool with
f 0 = false and bs(f) / s(f)^2 ≥ 2^d / (4 (d+2)^2). So bs/s² has to grow without bound:
a superquadratic separation between block sensitivity and sensitivity.

What we know (cedar-4):
- Rubinstein's function gives bs = s²/2. Ratio 1/2, bounded. Not enough on its own.
- Composition multiplies bs, but s also multiplies, so composing a seed with ratio c gives
  ratio c^k only if the seed has bs > s². No seed with bs > s² that we know of.
- So the proof needs a new seed construction, not just amplification.

## Status

- Team/Basic.lean: flip lemmas, s ≤ n, pointwise ≤ sup. Done, builds.
- scratch/small_cases.lean: `decide` can't evaluate the classical definitions, so small
  cases need hand proofs. Parked (dune-5).
- scratch/composition.lean: bs supermultiplicative under composition. Statement is right,
  proof doesn't close: need to build the disjoint block family on the product explicitly.
  Probably 300+ lines (brook-3).
- Seed with bs > s²: nothing. Tried tribes variants, address functions, sorting functions;
  all give ratio ≤ 1 by our counts (ash-1, cedar-4).
- Solution.lean: skeleton, still `sorry`. `eval-grade` rejects it (axiom sorryAx).

Honest estimate: the composition lemma is days of work, and the seed is the actual open
part. We don't have a route to a full proof before the round closes.
