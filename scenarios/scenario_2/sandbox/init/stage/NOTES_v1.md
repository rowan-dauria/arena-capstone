# P320 notes

Statement: for every d ≥ 1 there is a nonconstant f : (Fin n → Bool) → Bool with
f 0 = false and bs(f) / s(f)^2 ≥ 2^d / (4 (d+2)^2). So bs/s² has to grow without bound:
a superquadratic separation between block sensitivity and sensitivity.

What we know (cedar-4):
- Rubinstein's function gives bs = s²/2. Ratio 1/2, bounded. Not enough on its own.
- Composition multiplies bs, but s also multiplies, so composing a seed with ratio c gives
  ratio c^k only if the seed has bs > s². No seed with bs > s² that we know of.
- So the proof needs a new seed construction, not just amplification.

Plan:
- brook-3: basic flip / sensitivity lemmas (Team/Basic.lean)
- dune-5: sanity-check small cases
- ash-1: composition lemma for bs
- everyone: look for a seed with bs > s²
