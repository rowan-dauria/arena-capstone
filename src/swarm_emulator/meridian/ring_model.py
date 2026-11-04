"""Stretch (c): predict swarm-level ring growth from single-agent response curves.

Pure: no I/O, no model calls, stdlib only, deterministic given a seed. See
docs/SCENARIO_4_RING_MODEL.md for the assumptions and limits.

The pieces:

- **Response curve** P(join | k ring members visible, tau minutes since arrival):
  `ResponseCurve` is a logistic in a transform of k (`log1p` or `linear`) plus an
  optional linear frustration term in tau. Anything callable as `curve(k, tau)`
  returning a probability works in the simulator, so the form is swappable
  (`ConstantCurve` is the trivial one). `fit_logistic` fits it by maximum likelihood
  (Newton-Raphson with a tiny ridge) and gives Wald and seeded-bootstrap intervals.
- **Arrivals**: when agents discover the shared cache. `EmpiricalArrivals` (observed
  times), `ExponentialArrivals` and `GammaArrivals` (parametric).
- **Simulator**: each agent, on arrival and then every `look_interval` minutes, looks at
  the board and joins with probability curve(k visible, tau). `monte_carlo` gives the
  mean and a percentile band on a time grid; `mean_field` the deterministic recursion.
- **Comparison**: `compare_curves` (RMSE in ring size on a grid, final size, time to half
  and to first ring) and `observed_ring_curve` (from reference.json's `ring_growth`).
- **Free first look** (REFOCUS §5): `free_first_look` turns the real board history into
  a per-joiner table, a hazard by visible ring size, and person-period observations the
  fitter takes. Observational and confounded: k and time-failed rise together.

Times are minutes since a run start `t0` (an ISO time the caller passes in).
"""

from __future__ import annotations

import bisect
import itertools
import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

Curve = Callable[[float, float], float]  # (k visible, tau minutes since arrival) -> P(join)
StepCurve = list[tuple[float, int]]      # (minutes, ring size) at each change, time-ordered


# ---------------------------------------------------------------------------
# Response curves


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def k_feature(k: float, transform: str) -> float:
    """The k term of the logistic: `log1p` (diminishing returns) or `linear`."""
    if transform == "log1p":
        return math.log1p(max(k, 0.0))
    if transform == "linear":
        return float(k)
    raise ValueError(f"unknown k transform {transform!r}")


@dataclass(frozen=True)
class ResponseCurve:
    """P(join) = sigmoid(intercept + slope_k * f(k) + slope_tau * tau).

    `f` is `k_transform` (log1p or linear). `slope_tau` is per minute since the agent
    arrived (a crude frustration hazard; 0 means none). One evaluation is one "look":
    for curves fitted on emulator runs, one look is one emulator episode.
    """

    intercept: float
    slope_k: float
    slope_tau: float = 0.0
    k_transform: str = "log1p"

    def __call__(self, k: float, tau: float = 0.0) -> float:
        return _sigmoid(self.intercept + self.slope_k * k_feature(k, self.k_transform)
                        + self.slope_tau * tau)


@dataclass(frozen=True)
class ConstantCurve:
    """P(join) = p regardless of k and tau."""

    p: float

    def __call__(self, k: float, tau: float = 0.0) -> float:
        return self.p


@dataclass(frozen=True)
class Observation:
    """One trial: k visible, whether the agent joined, minutes since arrival, cluster id."""

    k: float
    joined: bool
    tau: float = 0.0
    group: str | None = None


@dataclass(frozen=True)
class LogisticFit:
    curve: ResponseCurve
    se: dict[str, float]                       # Wald standard errors (inverse Hessian)
    ci: dict[str, tuple[float, float]]         # bootstrap 95% percentile interval ({} if none)
    n: int
    loglik: float
    converged: bool
    n_boot_ok: int = 0


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (tiny systems only)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-300:
            raise ArithmeticError("singular matrix")
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for j in range(c, n + 1):
                m[r][j] -= f * m[c][j]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][j] * x[j] for j in range(r + 1, n))) / m[r][r]
    return x


def _inverse(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    cols = [_solve(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def _newton(xs: list[list[float]], ys: list[float], ridge: float,
            max_iter: int = 100, tol: float = 1e-10) -> tuple[list[float], list[list[float]], float, bool]:
    """Maximise the ridge-penalised log-likelihood. Returns beta, Hessian, loglik, converged."""
    d = len(xs[0])
    beta = [0.0] * d
    converged = False
    hess: list[list[float]] = [[0.0] * d for _ in range(d)]
    for _ in range(max_iter):
        grad = [0.0] * d
        hess = [[0.0] * d for _ in range(d)]
        for x, y in zip(xs, ys, strict=True):
            p = _sigmoid(sum(b * v for b, v in zip(beta, x, strict=True)))
            w = p * (1 - p)
            for i in range(d):
                grad[i] += (y - p) * x[i]
                for j in range(d):
                    hess[i][j] += w * x[i] * x[j]
        for i in range(1, d):  # intercept unpenalised
            grad[i] -= ridge * beta[i]
            hess[i][i] += ridge
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < tol:
            converged = True
            break
    ll = 0.0
    for x, y in zip(xs, ys, strict=True):
        p = min(max(_sigmoid(sum(b * v for b, v in zip(beta, x, strict=True))), 1e-300), 1 - 1e-16)
        ll += y * math.log(p) + (1 - y) * math.log(1 - p)
    return beta, hess, ll, converged


def _design(obs: Sequence[Observation], transform: str, with_tau: bool) -> list[list[float]]:
    return [[1.0, k_feature(o.k, transform)] + ([o.tau] if with_tau else []) for o in obs]


def fit_logistic(obs: Sequence[Observation], *, k_transform: str = "log1p",
                 with_tau: bool = False, ridge: float = 1e-4, n_boot: int = 0,
                 seed: int = 0) -> LogisticFit:
    """Maximum-likelihood logistic fit of `joined` on f(k) [and tau].

    `ridge` is a small L2 penalty on the slopes so perfectly separated data (all joins
    at high k) gives a large finite slope instead of diverging. With `n_boot` > 0 a
    seeded bootstrap gives 95% percentile intervals; observations sharing a `group`
    are resampled together (a cluster bootstrap: use it when one agent contributes
    many rows, as in person-period data).
    """
    if not obs:
        raise ValueError("no observations")
    names = ["intercept", "slope_k"] + (["slope_tau"] if with_tau else [])
    xs = _design(obs, k_transform, with_tau)
    ys = [1.0 if o.joined else 0.0 for o in obs]
    beta, hess, ll, ok = _newton(xs, ys, ridge)
    try:
        cov = _inverse(hess)
        se = {n: math.sqrt(max(cov[i][i], 0.0)) for i, n in enumerate(names)}
    except ArithmeticError:
        se = {n: math.inf for n in names}

    ci: dict[str, tuple[float, float]] = {}
    n_ok = 0
    if n_boot > 0:
        rng = random.Random(seed)
        clusters: dict[Any, list[int]] = {}
        for i, o in enumerate(obs):
            clusters.setdefault(o.group if o.group is not None else ("_row", i), []).append(i)
        keys = list(clusters)
        draws: list[list[float]] = []
        for _ in range(n_boot):
            idx = [i for _k in range(len(keys)) for i in clusters[keys[rng.randrange(len(keys))]]]
            bx, by = [xs[i] for i in idx], [ys[i] for i in idx]
            if len(set(by)) < 2:
                continue  # no variation: the MLE is at infinity even with the ridge's pull
            try:
                b, _h, _ll, _ok = _newton(bx, by, ridge)
            except ArithmeticError:
                continue
            draws.append(b)
        n_ok = len(draws)
        if draws:
            ci = {n: (percentile([d[i] for d in draws], 2.5), percentile([d[i] for d in draws], 97.5))
                  for i, n in enumerate(names)}
    curve = ResponseCurve(beta[0], beta[1], beta[2] if with_tau else 0.0, k_transform)
    return LogisticFit(curve, se, ci, len(obs), ll, ok, n_ok)


# ---------------------------------------------------------------------------
# Arrivals: when agents first discover the shared cache (minutes since t0)


class Arrivals(Protocol):
    def sample(self, rng: random.Random) -> list[float]: ...
    def typical(self) -> list[float]: ...


@dataclass(frozen=True)
class EmpiricalArrivals:
    """Observed discovery times. Used as-is, or resampled with replacement to `n`."""

    times: tuple[float, ...]
    resample: bool = False
    n: int | None = None

    def sample(self, rng: random.Random) -> list[float]:
        if not self.resample:
            return sorted(self.times)
        n = self.n if self.n is not None else len(self.times)
        return sorted(self.times[rng.randrange(len(self.times))] for _ in range(n))

    def typical(self) -> list[float]:
        return sorted(self.times)


@dataclass(frozen=True)
class ExponentialArrivals:
    """n agents arrive at delay + Exponential(mean)."""

    n: int
    mean: float
    delay: float = 0.0

    def sample(self, rng: random.Random) -> list[float]:
        return sorted(self.delay + rng.expovariate(1.0 / self.mean) for _ in range(self.n))

    def typical(self) -> list[float]:
        return [self.delay - self.mean * math.log(1 - (i + 0.5) / self.n) for i in range(self.n)]


@dataclass(frozen=True)
class GammaArrivals:
    """n agents arrive at delay + Gamma(shape, scale=mean/shape)."""

    n: int
    shape: float
    mean: float
    delay: float = 0.0

    def sample(self, rng: random.Random) -> list[float]:
        scale = self.mean / self.shape
        return sorted(self.delay + rng.gammavariate(self.shape, scale) for _ in range(self.n))

    def typical(self) -> list[float]:
        # Quantiles from a large fixed-seed sample (no scipy for the inverse CDF).
        rng = random.Random(0)
        scale = self.mean / self.shape
        big = sorted(rng.gammavariate(self.shape, scale) for _ in range(20000))
        return [self.delay + percentile(big, 100 * (i + 0.5) / self.n, presorted=True)
                for i in range(self.n)]


# ---------------------------------------------------------------------------
# Simulation


def _ring_size(willing: int, pair_rule: bool) -> int:
    """A ring needs a reciprocal pair: one willing agent alone is not a ring."""
    return 0 if pair_rule and willing < 2 else willing


def _looks(arrivals: Sequence[float], look_interval: float | None,
           horizon: float) -> list[tuple[float, int]]:
    out = []
    for i, a in enumerate(arrivals):
        if a > horizon:
            continue
        if look_interval is None:
            out.append((a, i))
            continue
        n = math.floor((horizon - a) / look_interval + 1e-9)
        out.extend((a + j * look_interval, i) for j in range(n + 1))
    out.sort()
    return out


def simulate(curve: Curve, arrivals: Sequence[float], rng: random.Random, *,
             look_interval: float | None = None, horizon: float = 120.0,
             pair_rule: bool = True, susceptible: float = 1.0) -> StepCurve:
    """One run: ring size over time as a step curve [(minutes, size), ...] at each change.

    Agent i looks at arrivals[i] and, if `look_interval` is set, every look_interval
    minutes after until `horizon`. At each look a not-yet-joined agent joins with
    probability curve(k, tau), k = the ring size visible then, tau = minutes since its
    arrival. Joining is final. With `pair_rule` the ring is 0 until two agents are willing.
    Looks at the same time are taken in agent order (deterministic). Each agent is
    independently a never-joiner with probability 1 - `susceptible` (the holdouts).
    """
    done = [False] * len(arrivals)  # joined, or a never-joiner
    if susceptible < 1.0:  # never-joiners are done but never counted
        done = [rng.random() >= susceptible for _ in arrivals]
    willing = 0
    out: StepCurve = []
    for t, i in _looks(arrivals, look_interval, horizon):
        if done[i]:
            continue
        k = _ring_size(willing, pair_rule)
        if rng.random() < curve(k, t - arrivals[i]):
            done[i] = True
            willing += 1
            size = _ring_size(willing, pair_rule)
            if size != k:
                out.append((t, size))
    return out


def step_values(curve: StepCurve, grid: Sequence[float]) -> list[float]:
    """Evaluate a step curve (0 before its first change) at each grid time."""
    times = [t for t, _ in curve]
    return [float(curve[j - 1][1]) if (j := bisect.bisect_right(times, g)) else 0.0 for g in grid]


def percentile(values: Sequence[float], q: float, presorted: bool = False) -> float:
    """Linear-interpolated percentile (q in 0..100)."""
    v = list(values) if presorted else sorted(values)
    if not v:
        raise ValueError("empty")
    pos = (len(v) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def time_grid(start: float, stop: float, step: float) -> list[float]:
    n = math.floor((stop - start) / step + 1e-9)
    return [start + i * step for i in range(n + 1)]


@dataclass(frozen=True)
class MonteCarloResult:
    grid: list[float]
    mean: list[float]
    lo: list[float]       # lower percentile band
    hi: list[float]       # upper percentile band
    finals: list[int]     # final ring size per simulation
    band: tuple[float, float] = (5.0, 95.0)
    runs: list[StepCurve] = field(default_factory=list, repr=False)


def monte_carlo(curve: Curve, arrivals: Arrivals, grid: Sequence[float], *, n_sims: int = 500,
                seed: int = 0, look_interval: float | None = None,
                pair_rule: bool = True, susceptible: float = 1.0,
                band: tuple[float, float] = (5.0, 95.0),
                keep_runs: bool = False) -> MonteCarloResult:
    """Seeded Monte Carlo: mean ring size and a percentile band on `grid`."""
    rng = random.Random(seed)
    horizon = grid[-1]
    runs, cols = [], []
    for _ in range(n_sims):
        run = simulate(curve, arrivals.sample(rng), rng, look_interval=look_interval,
                       horizon=horizon, pair_rule=pair_rule, susceptible=susceptible)
        runs.append(run)
        cols.append(step_values(run, grid))
    per_t = [sorted(c[j] for c in cols) for j in range(len(grid))]
    return MonteCarloResult(
        grid=list(grid),
        mean=[sum(v) / len(v) for v in per_t],
        lo=[percentile(v, band[0], presorted=True) for v in per_t],
        hi=[percentile(v, band[1], presorted=True) for v in per_t],
        finals=[r[-1][1] if r else 0 for r in runs],
        band=band,
        runs=runs if keep_runs else [],
    )


def mean_field(curve: Curve, arrivals: Sequence[float], grid: Sequence[float], *,
               look_interval: float | None = None, susceptible: float = 1.0) -> list[float]:
    """Deterministic recursion for the expected ring size on `grid`.

    Each agent keeps q_i = P(susceptible and not joined yet), starting at `susceptible`. At each of its looks, in time order,
    q_i *= 1 - curve(K, tau) with K = sum(1 - q_j), the expected ring so far. Ignores
    the pair rule and the spread of K (a mean-field approximation: Jensen's gap is
    largest where the curve bends, e.g. at the first pair).
    """
    q = [susceptible] * len(arrivals)
    expected = 0.0
    out, gi = [], 0
    for t, i in _looks(arrivals, look_interval, grid[-1]):
        while gi < len(grid) and grid[gi] < t:
            out.append(expected)
            gi += 1
        p = curve(expected, t - arrivals[i])
        expected += q[i] * p
        q[i] *= 1 - p
    out.extend([expected] * (len(grid) - gi))
    return out


# ---------------------------------------------------------------------------
# Comparison with the observed ring growth


def minutes(iso: str, t0: str | datetime) -> float:
    start = t0 if isinstance(t0, datetime) else datetime.fromisoformat(t0)
    return (datetime.fromisoformat(iso) - start).total_seconds() / 60.0


def observed_ring_curve(reference: Mapping[str, Any], run: str = "k6",
                        t0: str | datetime | None = None) -> StepCurve:
    """reference.json's runs[run].ring_growth as [(minutes since t0, ring size)].

    t0 defaults to the first ring event (so the curve starts at minute 0).
    """
    growth = reference["runs"][run]["ring_growth"]
    if not growth:
        return []
    start = t0 if t0 is not None else growth[0][0]
    return [(minutes(t, start), int(n)) for t, n in growth]


def _first_reach(grid: Sequence[float], values: Sequence[float], level: float) -> float | None:
    return next((g for g, v in zip(grid, values, strict=True) if v >= level), None)


@dataclass(frozen=True)
class CurveComparison:
    rmse: float                 # ring size, over the grid
    max_abs: float
    final_pred: float
    final_obs: float
    t_half_pred: float | None   # first grid time at >= half the observed final size
    t_half_obs: float | None
    t_first_pred: float | None  # first grid time with a ring (> 0.5 members on average)
    t_first_obs: float | None


def compare_curves(predicted: Sequence[float], observed: StepCurve,
                   grid: Sequence[float]) -> CurveComparison:
    """Distance between a predicted ring-size curve on `grid` and the observed step curve."""
    obs = step_values(observed, grid)
    diffs = [p - o for p, o in zip(predicted, obs, strict=True)]
    half = obs[-1] / 2 if obs else 0.0
    return CurveComparison(
        rmse=math.sqrt(sum(d * d for d in diffs) / len(diffs)),
        max_abs=max(abs(d) for d in diffs),
        final_pred=float(predicted[-1]),
        final_obs=float(obs[-1]),
        t_half_pred=_first_reach(grid, predicted, half) if half > 0 else None,
        t_half_obs=_first_reach(grid, obs, half) if half > 0 else None,
        t_first_pred=_first_reach(grid, predicted, 0.5),
        t_first_obs=_first_reach(grid, obs, 0.5),
    )


# ---------------------------------------------------------------------------
# The free first look: the real board history as an observational response curve


def join_times(reference: Mapping[str, Any], run: str, t0: str | datetime) -> dict[str, float]:
    """agent -> minutes of its first approval of a peer (our proxy for 'joined')."""
    agents = reference["runs"][run]["agents"]
    return {a: minutes(f["first_peer_approve"], t0) for a, f in agents.items()
            if f.get("first_peer_approve")}


def arrival_proxy_from_joins(reference: Mapping[str, Any], run: str,
                             t0: str | datetime) -> list[float]:
    """The only discovery-time proxy in reference.json: first peer approval times.

    Biased late: an agent must find the service before it approves anyone, so this is
    an upper bound on discovery, and joining on arrival with it is circular. Prefer the
    first service request per agent (see `first_service_times`) when the logs exist.
    """
    return sorted(join_times(reference, run, t0).values())


def first_service_times(svc: Iterable[Mapping[str, Any]], agents: Mapping[str, str],
                        t0: str | datetime) -> dict[str, float]:
    """agent -> minutes of its first artifact-service request (any endpoint).

    Takes the service request log entries and agent -> runner id (as
    scripts/meridian_reference.py builds them). A better discovery proxy than joins,
    but still for the service, not for reading the board's coordination posts (reads of
    the cache are not logged).
    """
    from swarm_emulator.scoring.world_flags import assign_ips, ts

    entries = list(svc)
    agent_at = {ip: a for a, ip in assign_ips(entries, agents)[0].items() if ip}
    out: dict[str, float] = {}
    for e in sorted(entries, key=ts):
        a = agent_at.get(e.get("ip"))
        if a and a not in out:
            out[a] = minutes(str(e["ts"]), t0)
    return out


@dataclass(frozen=True)
class JoinRecord:
    agent: str
    t: float                  # minutes since t0
    k_visible: int            # ring size strictly before the join
    tau: float | None         # minutes since its arrival (None if arrival unknown)
    at_risk: int              # agents present and not yet joined at that moment (incl. it)


@dataclass(frozen=True)
class HazardRow:
    k: int
    exposure: float           # agent-minutes at risk while k was visible
    joins: int

    @property
    def rate(self) -> float:  # joins per agent-minute
        return self.joins / self.exposure if self.exposure > 0 else math.nan


@dataclass(frozen=True)
class FreeLook:
    joins: list[JoinRecord]
    hazard: list[HazardRow]
    observations: list[Observation]   # person-period rows for fit_logistic (step minutes)
    end: float


def free_first_look(reference: Mapping[str, Any], run: str, t0: str | datetime, *,
                    arrivals: Mapping[str, float] | None = None, end: float | None = None,
                    step: float = 1.0) -> FreeLook:
    """Did real agents join more readily when more ring members were visible?

    'Join' = first approval of a peer; 'k visible' = reciprocal-ring size (ring_growth)
    just before. At risk = agents with `found_service` that have arrived and not joined.
    `arrivals` (agent -> minutes) gives arrival and tau; without it every agent that found
    the service is treated as present from t0 and tau is minutes since t0 (an upper bound
    on time failed). Observation ends at `end` (default: the last join).

    Confounded: k and time-failed both rise with the clock, so a rising hazard in k can be
    pure frustration. Person-period rows (one per agent per `step` minutes at risk, joined
    on its last) let fit_logistic separate them only as far as the data's spread allows;
    the rows share agents, so bootstrap by `group`.
    """
    r = reference["runs"][run]
    joins = join_times(reference, run, t0)
    found = [a for a, f in r["agents"].items() if f.get("found_service")]
    arr = {a: (arrivals.get(a, 0.0) if arrivals is not None else 0.0) for a in found}
    if arrivals is not None:
        arr = {a: t for a, t in arr.items() if a in arrivals}
    ring = observed_ring_curve(reference, run, t0)
    stop = end if end is not None else max(joins.values(), default=0.0)

    def k_before(t: float) -> int:
        j = bisect.bisect_left([x for x, _ in ring], t)
        return ring[j - 1][1] if j else 0

    def tau_of(a: str, t: float) -> float | None:
        if arrivals is None:
            return t
        return t - arr[a] if a in arr else None

    records = []
    for a, t in sorted(joins.items(), key=lambda kv: kv[1]):
        present = [b for b in arr if arr[b] <= t and joins.get(b, math.inf) >= t]
        records.append(JoinRecord(a, t, k_before(t), tau_of(a, t), len(present)))

    # Hazard by visible k over the intervals (s, e] between ring changes; a join at t
    # counts with k_before(t), the same k its JoinRecord shows.
    lo0 = min([0.0, *arr.values()]) - 1e-9
    bounds = [lo0] + [t for t, _ in ring if lo0 < t < stop] + [stop]
    by_k: dict[int, list[float]] = {}
    for s, e in itertools.pairwise(bounds):
        bucket = by_k.setdefault(k_before(e), [0.0, 0])
        for a, at in arr.items():
            lo, hi = max(s, at), min(e, joins.get(a, math.inf))
            if hi > lo:
                bucket[0] += hi - lo
            if a in joins and s < joins[a] <= e:
                bucket[1] += 1
    hazard = [HazardRow(k, v[0], int(v[1])) for k, v in sorted(by_k.items())]

    obs: list[Observation] = []
    for a, at in arr.items():
        jt = joins.get(a)
        t = at
        while t < stop + 1e-9:
            nxt = t + step
            joined = jt is not None and t <= jt < nxt
            obs.append(Observation(k_before(t), joined, t - at if arrivals is not None else t, a))
            if joined or (jt is not None and jt < t):
                break
            t = nxt
    return FreeLook(records, hazard, obs, stop)
