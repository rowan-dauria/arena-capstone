"""Cost of swarm_audit runs from their logs, plus a projection for Experiment 1.

    uv run python scripts/cost_report.py logs/dev --latest   # newest log in a dir
    uv run python scripts/cost_report.py logs/pilot          # every log in a dir
    uv run python scripts/cost_report.py run.eval --project configs/exp1.yaml

Prices come from configs/prices.yaml (scripts/update_prices.py). Costs are
recomputed from logged token usage, so this works on any log. A role whose model
has no price is reported as unpriced, never counted as $0.

The projection takes this run's mean tokens per sample for each role, prices them
at the roles' models in the projected stage (falling back to this run's models
where that stage's ${VARS} are unset), and multiplies by cells x epochs. It
assumes the same tokens per sample, so a dev run with fewer turns underestimates.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from inspect_ai.log import read_eval_log

from swarm_emulator import repo_path
from swarm_emulator.costs import (
    PRICES,
    PriceTable,
    load_prices,
    mean_role_usage,
    missing_prices,
    project,
    role_costs,
    role_models,
    sample_cost,
)
from swarm_emulator.stage import load_stage

EXP1_CELLS = 10  # SPEC §1: 8 cells + 2 controls (until config.experiment_1_grid exists)


def money(x: float | None) -> str:
    return "unpriced" if x is None else f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def log_paths(target: Path, latest: bool) -> list[Path]:
    if target.is_file():
        return [target]
    paths = sorted(target.glob("*.eval"))
    return paths[-1:] if latest else paths


def projected_models(stage_path: Path, fallback: dict[str, str]) -> tuple[dict[str, str], int]:
    raw = yaml.safe_load(stage_path.read_text())
    try:
        models = load_stage(stage_path)["roles"]
    except KeyError as ex:
        print(f"  ({stage_path.name}: {ex.args[0]}; pricing at this run's models)")
        models = {}
    return {**fallback, **models}, int(raw.get("epochs", 1))


def report(path: Path, prices: PriceTable, project_stage: Path | None) -> None:
    log = read_eval_log(path)
    samples = log.samples or []
    models = role_models(log)
    print(f"cost: {path.name}  ({len(samples)} sample(s); prices fetched {prices.fetched or '?'})")

    for m in missing_prices(models.values(), prices):
        print(f"  WARNING no price for {m}: run scripts/update_prices.py or add it to {PRICES}")

    by_role = role_costs(log.stats.role_usage or {}, models, prices)
    total = None if None in by_role.values() else sum(c for c in by_role.values() if c)
    per = None if total is None or not samples else total / len(samples)
    print(f"  total {money(total)}   per sample {money(per)}")
    for role, cost in sorted(by_role.items(), key=lambda kv: -(kv[1] or 0)):
        print(f"    {role:<11} {money(cost):>10}  {models.get(role, '?')}")

    cells: dict[str, list[float | None]] = defaultdict(list)
    for s in samples:
        cells[str(s.id)].append(sample_cost(s, models, prices))
    if len(cells) > 1 or any(len(v) > 1 for v in cells.values()):
        print("  by cell (mean / max):")
        for cell, costs in sorted(cells.items()):
            if None in costs:
                print(f"    {cell:<40} unpriced")
            else:
                print(f"    {cell:<40} {money(sum(costs) / len(costs)):>10} / {money(max(costs))}")

    if project_stage and samples:
        proj_models, epochs = projected_models(project_stage, models)
        n = EXP1_CELLS * epochs
        cost = project(mean_role_usage(samples), proj_models, prices, n)
        print(f"  projection for {project_stage.stem}: {EXP1_CELLS} cells x {epochs} epochs = {n} "
              f"samples per target model ~ {money(cost)} (same tokens per sample as this run)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--latest", action="store_true", help="only the newest log in a directory")
    ap.add_argument("--project", type=Path, default=repo_path("configs/exp1.yaml"),
                    help="stage config to project the cost of (default configs/exp1.yaml)")
    ap.add_argument("--no-project", action="store_true")
    args = ap.parse_args()

    paths = log_paths(args.path, args.latest)
    if not paths:
        print(f"no .eval logs in {args.path}", file=sys.stderr)
        return 1
    prices = load_prices(repo_path(PRICES))
    for path in paths:
        report(path, prices, None if args.no_project else args.project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
