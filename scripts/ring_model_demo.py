"""Stretch (c) demo: predicted vs observed ring growth for the 24-agent run (k6).

    uv run python scripts/ring_model_demo.py [--sims 500] [--seed 0]

No model calls. Reads scenarios/scenario_4/reference.json and, if present, the local
copy of the preserved service log (data/meridian_ref/, from
scripts/meridian_reference.py) for the agents' discovery times.

The response curve below is a PLACEHOLDER ASSUMPTION, not data: the real curve comes
from the emulator seeds s4__k6__ring{0,3,10,17} (docs/SCENARIO_4_RING_MODEL.md). The
"free first look" section is fitted to the real board history (observational,
confounded) and its simulation is in-sample, so it is a sanity check, not a prediction.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta

from swarm_emulator import repo_path
from swarm_emulator.meridian.ring_model import (
    EmpiricalArrivals,
    GammaArrivals,
    ResponseCurve,
    compare_curves,
    first_service_times,
    fit_logistic,
    free_first_look,
    mean_field,
    minutes,
    monte_carlo,
    observed_ring_curve,
    step_values,
    time_grid,
)

REFERENCE = repo_path("scenarios/scenario_4/reference.json")
LOGS = repo_path("data/meridian_ref/2026-10-24_k6")
# Run start: the k6 eval log's file name (scripts/meridian_reference.py, K6_EVAL).
T0 = "2026-10-24T16:19:57+00:00"
HORIZON, STEP = 100.0, 1.0      # minutes after T0 (the ring stopped growing at ~86)

# ASSUMPTION (placeholder, not fitted): per look, every 2 minutes,
# P(join) = sigmoid(-7 + 1.0*log(1+k) + 0.06*minutes since arrival).
PLACEHOLDER = ResponseCurve(intercept=-7.0, slope_k=1.0, slope_tau=0.06, k_transform="log1p")
LOOK_EVERY = 2.0
# ASSUMPTION: a quarter of agents never join (the real run had 5 holdouts of 22 that found
# the service; the emulator would estimate this as P(no join) at the largest k).
SUSCEPTIBLE = 0.75


def local_arrivals() -> tuple[dict[str, float], float] | None:
    """(agent -> minutes of its first service request, minute of the last request),
    from the local logs if present."""
    log, issues = LOGS / "svc_state/requests.log", LOGS / "issues.json"
    if not (log.exists() and issues.exists()):
        return None
    svc = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
    agents = {r["agent_id"]: json.loads((LOGS / "runner_creds" / f"{r['agent_id']}.json")
                                        .read_text())["runner_id"]
              for r in json.loads(issues.read_text()) if r["tier"] == "C"}
    return first_service_times(svc, agents, T0), minutes(svc[-1]["ts"], T0)


def clock(m: float) -> str:
    return (datetime.fromisoformat(T0) + timedelta(minutes=m)).strftime("%H:%M")


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:5.1f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    ref = json.loads(REFERENCE.read_text())
    observed = observed_ring_curve(ref, "k6", T0)
    grid = time_grid(0.0, HORIZON, STEP)

    local = local_arrivals()
    found, end = local if local else (None, None)
    if found:
        arrivals = EmpiricalArrivals(tuple(sorted(found.values())))
        src = f"first service request per agent (local logs; {len(found)} agents)"
    else:
        arrivals = GammaArrivals(n=22, shape=2.0, mean=8.0, delay=1.0)
        src = "ASSUMPTION: 22 agents, 1 min + Gamma(shape 2, mean 8 min) (no local logs)"
    print(f"k6 run, t0 {T0}. Arrivals: {src}")
    print(f"Response curve: PLACEHOLDER ASSUMPTION, not data: {PLACEHOLDER}, "
          f"a look every {LOOK_EVERY:g} min, susceptible {SUSCEPTIBLE:g} (ASSUMPTION)")

    mc = monte_carlo(PLACEHOLDER, arrivals, grid, n_sims=args.sims, seed=args.seed,
                     look_interval=LOOK_EVERY, susceptible=SUSCEPTIBLE)
    mf = mean_field(PLACEHOLDER, arrivals.typical(), grid, look_interval=LOOK_EVERY,
                    susceptible=SUSCEPTIBLE)
    obs = step_values(observed, grid)
    print(f"\n  min  clock  observed  MC mean [5%, 95%]  mean-field   ({args.sims} sims, "
          f"seed {args.seed})")
    for i in range(0, len(grid), 10):
        print(f"  {grid[i]:4.0f}  {clock(grid[i])}  {obs[i]:6.0f}    {mc.mean[i]:5.1f} "
              f"[{mc.lo[i]:4.0f}, {mc.hi[i]:4.0f}]  {mf[i]:6.1f}")
    for name, pred in (("MC mean", mc.mean), ("mean-field", mf)):
        c = compare_curves(pred, observed, grid)
        print(f"  {name:10s} RMSE {c.rmse:.2f} members; final {c.final_pred:.1f} vs "
              f"{c.final_obs:.0f}; half-size at {fmt(c.t_half_pred)} vs {fmt(c.t_half_obs)} min; "
              f"first ring at {fmt(c.t_first_pred)} vs {fmt(c.t_first_obs)} min")

    print("\nFree first look (real board history; observational, k confounded with time failed)")
    look = free_first_look(ref, "k6", T0, arrivals=found, end=end)
    print(f"  observed until minute {look.end:.0f}"
          + ("" if end else " (the last join: no run end without the local logs)"))
    print("  joiner         clock  k visible  min since arrival  at risk")
    for j in look.joins:
        print(f"  {j.agent:14s} {clock(j.t)}  {j.k_visible:3d}  {fmt(j.tau)}  {j.at_risk:3d}")
    print("  hazard by k visible: k  agent-min  joins  per agent-hour")
    for h in look.hazard:
        print(f"    {h.k:3d}  {h.exposure:7.1f}  {h.joins:3d}  {60 * h.rate:6.2f}")
    fit = fit_logistic(look.observations, with_tau=True, n_boot=200, seed=args.seed)
    ci = {k: f"[{lo:+.2f}, {hi:+.2f}]" for k, (lo, hi) in fit.ci.items()}
    print(f"  per-minute logistic, log(1+k) + tau, {fit.n} person-minutes: "
          f"slope_k {fit.curve.slope_k:+.2f} {ci.get('slope_k')}, "
          f"slope_tau {fit.curve.slope_tau:+.3f}/min {ci.get('slope_tau')} "
          f"(cluster bootstrap by agent, {fit.n_boot_ok} ok)")
    insample = monte_carlo(fit.curve, arrivals, grid, n_sims=args.sims, seed=args.seed,
                           look_interval=1.0)
    c = compare_curves(insample.mean, observed, grid)
    print(f"  in-sample check (that fit simulated, looks every minute): RMSE {c.rmse:.2f}, "
          f"final {c.final_pred:.1f} vs {c.final_obs:.0f}, half-size at {fmt(c.t_half_pred)} vs "
          f"{fmt(c.t_half_obs)} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
