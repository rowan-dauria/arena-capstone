#!/usr/bin/env bash
# Reproduce scenario 4's free pipeline end to end: no paid model/API calls (mockllm only).
#
#   scripts/reproduce_scenario_4.sh
#
# 1. reference data (downloaded once from the pinned dataset if data/meridian_ref/ is absent)
# 2. rebuild the world (data/meridian_world/) and verify it against world_manifest.json
# 3. regenerate the seeds from cells.yaml (the ablation matrix) and the template
# 4. lint every cell (quorum vs compose, beats files; skeleton cells reported, not run)
# 5. scenario 4 unit tests
# 6. the Docker mock-swarm check: the baseline beats promote the target's build at quorum 6,
#    and the no-swarm control releases nothing and promotes nothing
# Needs docker. Exits non-zero at the first failing step.
set -euo pipefail
cd "$(dirname "$0")/.."

step() { echo; echo "=== $* ==="; }
start=$SECONDS

if [ ! -d data/meridian_ref/2026-10-24_k6 ] || [ ! -d data/meridian_ref/2026-09-17_kUFz3 ]; then
  step "reference data (download)"
  uv run python scripts/meridian_reference.py
fi

step "rebuild the world"
uv run python scripts/rebuild_meridian_world.py
uv run python scripts/rebuild_meridian_world.py --check

step "regenerate seeds"
uv run python scripts/gen_seeds.py scenarios/scenario_4

step "lint cells and beats"
uv run python scripts/check_scenario_4.py

step "unit tests (scenario 4)"
uv run pytest -q tests/test_scenario_4.py tests/test_scenario_4_cells.py \
  tests/test_meridian_swarm.py tests/test_meridian_world.py tests/test_world_flags.py

step "docker mock-swarm check (baseline + control)"
uv run python scripts/check_meridian_swarm.py

echo
echo "scenario 4 reproduced OK in $((SECONDS - start)) s"
