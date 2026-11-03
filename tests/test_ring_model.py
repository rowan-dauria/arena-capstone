"""Stretch (c) ring-growth model: fitter, simulator, comparison, reference loading."""

from __future__ import annotations

import json
import math
import random

import pytest

from swarm_emulator import repo_path
from swarm_emulator.meridian.ring_model import (
    ConstantCurve,
    EmpiricalArrivals,
    ExponentialArrivals,
    GammaArrivals,
    Observation,
    ResponseCurve,
    compare_curves,
    fit_logistic,
    free_first_look,
    mean_field,
    monte_carlo,
    observed_ring_curve,
    percentile,
    simulate,
    step_values,
    time_grid,
)

T0 = "2026-10-24T16:00:00+00:00"


def synthetic(truth: ResponseCurve, per_k: int, seed: int) -> list[Observation]:
    rng = random.Random(seed)
    return [Observation(k, rng.random() < truth(k)) for k in (0, 3, 10, 17) for _ in range(per_k)]


@pytest.mark.parametrize("transform", ["log1p", "linear"])
def test_fitter_recovers_known_logistic(transform: str) -> None:
    truth = ResponseCurve(-2.0, 1.0 if transform == "log1p" else 0.25, k_transform=transform)
    fit = fit_logistic(synthetic(truth, 500, seed=1), k_transform=transform)
    assert fit.converged
    assert fit.curve.intercept == pytest.approx(truth.intercept, abs=0.3)
    assert fit.curve.slope_k == pytest.approx(truth.slope_k, abs=4 * fit.se["slope_k"])
    assert fit.se["slope_k"] < 0.2 * abs(truth.slope_k)


def test_fitter_bootstrap_is_seeded_and_covers_truth() -> None:
    truth = ResponseCurve(-2.0, 1.0)
    obs = synthetic(truth, 100, seed=2)
    a = fit_logistic(obs, n_boot=20, seed=7)
    b = fit_logistic(obs, n_boot=20, seed=7)
    assert a.ci == b.ci and a.n_boot_ok == 20
    lo, hi = a.ci["slope_k"]
    assert lo < truth.slope_k < hi


def test_fitter_with_tau_and_separated_data_stays_finite() -> None:
    obs = [Observation(k, k >= 10, tau=float(k)) for k in (0, 3, 10, 17) for _ in range(5)]
    fit = fit_logistic(obs, with_tau=True)
    assert all(math.isfinite(v) for v in (fit.curve.intercept, fit.curve.slope_k,
                                           fit.curve.slope_tau))
    assert fit.curve(17, 17) > 0.9
    assert fit.curve(0, 0) < 0.1


def test_curves() -> None:
    c = ResponseCurve(-3.0, 1.0, slope_tau=0.05)
    assert c(0) < c(3) < c(17)
    assert c(3, 0) < c(3, 30)
    assert ConstantCurve(0.3)(99, 99) == 0.3
    with pytest.raises(ValueError):
        ResponseCurve(0, 1, k_transform="sqrt")(1)


def test_simulator_is_deterministic_under_seed() -> None:
    curve, arr = ResponseCurve(-3.0, 1.0, 0.05), ExponentialArrivals(n=15, mean=10.0)
    grid = time_grid(0, 60, 2)
    a = monte_carlo(curve, arr, grid, n_sims=30, seed=3, look_interval=5)
    b = monte_carlo(curve, arr, grid, n_sims=30, seed=3, look_interval=5)
    c = monte_carlo(curve, arr, grid, n_sims=30, seed=4, look_interval=5)
    assert a == b
    assert a.mean != c.mean
    assert all(lo <= hi for lo, hi in zip(a.lo, a.hi, strict=True))  # a skewed mean may sit outside


@pytest.mark.parametrize("look", [None, 3.0])
def test_p0_stays_empty_and_p1_grows_to_arrivals(look: float | None) -> None:
    arrivals = [1.0, 2.0, 4.0, 8.0, 9.0, 15.0, 30.0, 200.0]  # the last is past the horizon
    rng = random.Random(0)
    assert simulate(ConstantCurve(0.0), arrivals, rng, look_interval=look, horizon=60) == []
    full = simulate(ConstantCurve(1.0), arrivals, rng, look_interval=look, horizon=60)
    assert full[0] == (2.0, 2)  # the pair rule: the first ring is a pair
    assert full[-1] == (30.0, 7)
    grid = time_grid(0, 60, 1)
    assert mean_field(ConstantCurve(0.0), arrivals, grid, look_interval=look)[-1] == 0
    assert mean_field(ConstantCurve(1.0), arrivals, grid, look_interval=look)[-1] == 7
    emp = EmpiricalArrivals(tuple(arrivals))
    mc = monte_carlo(ConstantCurve(1.0), emp, grid, n_sims=5, look_interval=look)
    assert mc.finals == [7] * 5


def test_susceptible_fraction_caps_the_ring() -> None:
    arrivals = [float(i) for i in range(40)]
    grid = time_grid(0, 60, 1)
    assert mean_field(ConstantCurve(1.0), arrivals, grid, susceptible=0.5)[-1] == 20
    mc = monte_carlo(ConstantCurve(1.0), EmpiricalArrivals(tuple(arrivals)), grid,
                     n_sims=50, susceptible=0.5)
    assert 15 < sum(mc.finals) / 50 < 25


def test_repeated_looks_let_frustration_act() -> None:
    curve = ResponseCurve(-8.0, 0.0, slope_tau=0.2)  # nobody joins on arrival
    arrivals = [0.0] * 10
    grid = time_grid(0, 60, 1)
    assert mean_field(curve, arrivals, grid)[-1] < 0.01
    assert mean_field(curve, arrivals, grid, look_interval=2)[-1] > 9


def test_arrival_models() -> None:
    e = ExponentialArrivals(n=10, mean=5.0, delay=1.0)
    g = GammaArrivals(n=10, shape=2.0, mean=5.0)
    for m in (e, g):
        t = m.typical()
        assert len(t) == 10 and t == sorted(t) and t == m.typical()
        assert len(m.sample(random.Random(0))) == 10
    assert min(e.typical()) > 1.0
    r = EmpiricalArrivals((3.0, 1.0, 2.0), resample=True, n=6).sample(random.Random(0))
    assert len(r) == 6 and set(r) <= {1.0, 2.0, 3.0}


def test_comparison_is_zero_for_identical_curves() -> None:
    observed = [(5.0, 2), (12.0, 5), (20.0, 9)]
    grid = time_grid(0, 30, 1)
    c = compare_curves(step_values(observed, grid), observed, grid)
    assert c.rmse == 0 and c.max_abs == 0
    assert c.t_half_pred == c.t_half_obs == 12.0 and c.t_first_pred == c.t_first_obs == 5.0
    worse = compare_curves([v + 1 for v in step_values(observed, grid)], observed, grid)
    assert worse.rmse == pytest.approx(1.0)


def test_step_values_and_percentile() -> None:
    assert step_values([(1.0, 2), (3.0, 4)], [0.0, 1.0, 2.0, 3.0, 9.0]) == [0, 2, 2, 4, 4]
    assert percentile([1, 2, 3, 4, 5], 50) == 3 and percentile([0, 10], 25) == 2.5


def test_observed_curve_loads_from_reference_json() -> None:
    ref = json.loads(repo_path("scenarios/scenario_4/reference.json").read_text())
    curve = observed_ring_curve(ref, "k6")
    assert curve[0] == (0.0, 2)
    assert [n for _, n in curve] == sorted(n for _, n in curve)
    assert [t for t, _ in curve] == sorted(t for t, _ in curve)
    assert curve[-1][1] == ref["runs"]["k6"]["summary"]["in_ring"]
    shifted = observed_ring_curve(ref, "k6", t0=ref["runs"]["k6"]["ring_growth"][0][0][:11]
                                  + "16:00:00+00:00")
    assert shifted[0][0] == pytest.approx(curve[0][0] + 52 + 14 / 60)
    assert observed_ring_curve(ref, "kUFz3")[-1][1] == ref["runs"]["kUFz3"]["summary"]["in_ring"]


def tiny_reference() -> dict:
    def agent(found: bool, approve: str | None) -> dict:
        return {"found_service": found, "first_peer_approve": approve}

    return {"runs": {"r": {
        "ring_growth": [["2026-10-24T16:10:00+00:00", 2], ["2026-10-24T16:20:00+00:00", 3]],
        "agents": {"a": agent(True, "2026-10-24T16:05:00+00:00"),
                   "b": agent(True, "2026-10-24T16:10:00+00:00"),
                   "c": agent(True, "2026-10-24T16:20:00+00:00"),
                   "d": agent(True, None),
                   "e": agent(False, None)},
    }}}


def test_free_first_look_on_a_tiny_board() -> None:
    look = free_first_look(tiny_reference(), "r", T0, end=30.0)
    assert [(j.agent, j.t, j.k_visible, j.at_risk) for j in look.joins] == [
        ("a", 5.0, 0, 4), ("b", 10.0, 0, 3), ("c", 20.0, 2, 2)]
    by_k = {h.k: h for h in look.hazard}
    assert by_k[0].joins == 2 and by_k[0].exposure == pytest.approx(5 + 10 + 10 + 10)
    assert by_k[2].joins == 1 and by_k[2].exposure == pytest.approx(10 + 10)
    assert by_k[3].joins == 0 and by_k[3].exposure == pytest.approx(10)
    assert sum(o.joined for o in look.observations) == 3
    assert {o.group for o in look.observations} == {"a", "b", "c", "d"}  # e never found it

    late = free_first_look(tiny_reference(), "r", T0, arrivals={"a": 1, "b": 1, "c": 18, "d": 1})
    assert late.joins[2].tau == 2.0 and late.joins[2].at_risk == 2


def test_free_first_look_on_the_reference() -> None:
    ref = json.loads(repo_path("scenarios/scenario_4/reference.json").read_text())
    look = free_first_look(ref, "k6", "2026-10-24T16:19:57+00:00")
    k6 = ref["runs"]["k6"]["summary"]
    assert len(look.joins) == sum(h.joins for h in look.hazard) == k6["approved_peer"]
    assert look.joins[0].k_visible == 0
