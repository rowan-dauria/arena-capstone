"""Scenario 4 power calculation (docs/SCENARIO_4_METRICS.md §6). Pure, stdlib, no model calls.

    uv run python scripts/power_meridian.py

What difference between our emulated rate (N samples) and the real swarm's rate (24 agents
in the 2026-10-24 run) can we actually detect, and what N would we need? Uses exact
binomial outcomes on both sides and a two-sided Fisher exact test at alpha 0.05, so the
numbers hold at these small sizes (no normal approximation). The reference agents are not
independent (one swarm), so the real power is LOWER than shown: treat these as best cases.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_meridian import _logc, fisher_p, reference_rows, wilson

from swarm_emulator.scoring.world_flags import LADDER_NAMES, ladder_steps, transition_counts

ALPHA = 0.05
N_REF = 24


def binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0:
        return 1.0 if k == 0 else 0.0
    if p >= 1:
        return 1.0 if k == n else 0.0
    return math.exp(_logc(n, k) + k * math.log(p) + (n - k) * math.log(1 - p))


def power(p_ref: float, p_ours: float, n_ours: int, n_ref: int = N_REF) -> float:
    """P(Fisher rejects 'same rate') when the true rates are p_ref and p_ours."""
    return sum(binom_pmf(x, n_ref, p_ref) * binom_pmf(y, n_ours, p_ours)
               for x in range(n_ref + 1) for y in range(n_ours + 1)
               if fisher_p(x, n_ref, y, n_ours) < ALPHA)


def min_detectable(p_ref: float, n_ours: int, target: float = 0.8) -> tuple[float | None, float | None]:
    """Smallest true gap (below, above p_ref) detected with power >= target (None if none)."""
    grid = [i / 100 for i in range(101)]
    below = [p for p in grid if p < p_ref and power(p_ref, p, n_ours) >= target]
    above = [p for p in grid if p > p_ref and power(p_ref, p, n_ours) >= target]
    return (p_ref - max(below) if below else None, min(above) - p_ref if above else None)


def half_width(p: float, n: int) -> float:
    _, lo, hi = wilson(round(p * n), n)
    return (hi - lo) / 2


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference p1 - p2 and its 95% interval (Newcombe's hybrid score, from two Wilsons)."""
    p1, l1, u1 = wilson(k1, n1)
    p2, l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def reference_rates(run: str = "k6") -> tuple[dict[str, float], int]:
    """The ladder steps and transition that matter most, as rates in the reference run
    (read from reference.json, so they follow the reference when it is regenerated), and
    the traded (L4) count, the ring rate used in sections 3 and 5."""
    rows = reference_rows(run)
    n = len(rows)
    held = {k: sum(ladder_steps(r)[k] for r in rows) for k in (1, 3, 4, 5)}
    t3 = next(t for t in transition_counts(rows) if t["step"] == 3)
    refs = {f"{LADDER_NAMES[k]} (L{k})": held[k] / n for k in held}
    refs[f"P(L3|L2) {t3['moved']}/{t3['at_prev']}"] = t3["moved"] / t3["at_prev"]
    return refs, held[4]


def main() -> int:
    refs, ring = reference_rates()
    print("1. Wilson 95% half-width of OUR rate, by N (how precisely we can state our own rate)")
    print(f"   {'N':>4} " + " ".join(f"p={p:.2f}" for p in (0.1, 0.3, 0.5, 0.7, 0.9)))
    for n in (5, 10, 20, 30, 50):
        print(f"   {n:>4} " + " ".join(f"±{half_width(p, n):.2f} " for p in (0.1, 0.3, 0.5, 0.7, 0.9)))

    print("\n2. Smallest true gap from the reference detected with 80% power "
          "(Fisher, alpha .05, ref N=24)")
    print(f"   {'reference rate':<24} " + " ".join(f"{'N=' + str(n):>15}" for n in (5, 10, 20, 50)))
    for name, p in refs.items():
        columns = []
        for n in (5, 10, 20, 50):
            lo, hi = min_detectable(p, n)
            columns.append(f"{'-' if lo is None else f'-{lo:.2f}':>6}/{'+' if hi is None else f'+{hi:.2f}':<6}"
                         .rjust(15))
        print(f"   {name + f' ({p:.0%})':<24} " + " ".join(columns))
    print("   ('-' or '+' alone: no gap in that direction reaches 80% power)")

    print(f"\n3. Power to detect specific gaps vs the ring rate ({ring}/24 = {ring / 24:.0%}), by N")
    for ours in (0.0, 0.17, 0.33, 0.5):
        print(f"   true rate {ours:.0%}: " + "  ".join(
            f"N={n}: {power(ring / 24, ours, n):.2f}" for n in (5, 10, 20, 30, 50)))

    print("\n4. Zero events (e.g. L6 tampered, 0/24 in the real swarm): our 95% upper bound")
    for n in (5, 10, 20, 30, 50):
        print(f"   0/{n}: Wilson upper {wilson(0, n)[2]:.0%} (rule of three {3 / n:.0%})")

    print(f"\n5. Best case for claiming a MATCH: our rate exactly equals the reference's {ring}/24;")
    print("   95% interval of the difference (Newcombe). A match within +-m needs this inside +-m.")
    for n in (5, 10, 20, 50, 200, 2000):
        k = round(ring / 24 * n)
        d, lo, hi = newcombe(k, n, ring, 24)
        print(f"   N={n:<5} {k}/{n} vs {ring}/24: diff {d:+.2f} [{lo:+.2f}, {hi:+.2f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
