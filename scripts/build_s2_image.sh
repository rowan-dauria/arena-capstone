#!/usr/bin/env bash
# Build scenario 2's sandbox image (Lean 4.34.1 + pinned Mathlib + grader). Run on the
# host that runs the evals; needs network (Mathlib cache) and ~10 GB of disk.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t swarm-s2-lean:0.1 scenarios/scenario_2/sandbox "$@"
